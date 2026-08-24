//! Platform seam for cooperative process termination. The lifecycle state
//! machine calls this named boundary instead of encoding Unix signal names
//! inline, keeping the wire protocol's grace/force/reap semantics
//! platform-neutral (apps/desktop/README.md "Supported boundary"). A future
//! Windows port supplies a Job-Object implementation behind the same
//! signature; forced kill + reap stay on portable `std::process::Child`.

/// Ask ONE process to terminate cooperatively. Returns false when it is
/// already gone or cannot be signalled.
///
/// **Not the shutdown ladder's primitive any more (#467).** Signalling only
/// the direct child is what let a grandchild outlive a complete
/// grace/TERM/KILL/reap sequence and reparent to launchd, still holding a
/// LanceDB staging directory. Use [`request_terminate_group`] there; this
/// per-PID form is retained because a caller that must NOT signal a whole
/// group has no other option — notably a test signalling a process that
/// shares the test runner's own group, where `killpg` would take down the
/// harness.
///
/// `#[allow(dead_code)]`: no production caller today, by design.
#[allow(dead_code)]
#[cfg(unix)]
pub fn request_terminate(pid: u32) -> bool {
    let Ok(pid) = i32::try_from(pid) else {
        return false;
    };
    // SAFETY: pid is the retained, validated direct-child PID; SIGTERM only.
    (unsafe { libc::kill(pid, libc::SIGTERM) }) == 0
}

/// Ask an entire process group to terminate cooperatively. #467.
///
/// The group-wide twin of [`request_terminate`]. The supervisor's child is
/// spawned into its own group, so this reaches the descendants that the
/// per-PID `kill` never could — a `tools.notebook_ingest` grandchild holding
/// a notebook's LanceDB staging directory, in the case #467 measured.
#[cfg(unix)]
pub fn request_terminate_group(pgid: u32) -> bool {
    let Ok(pgid) = i32::try_from(pgid) else {
        return false;
    };
    // SAFETY: pgid is a group this process created via `process_group(0)`;
    // SIGTERM only.
    (unsafe { libc::killpg(pgid, libc::SIGTERM) }) == 0
}

#[cfg(not(unix))]
pub fn request_terminate_group(_pgid: u32) -> bool {
    false
}

/// Owns the means of killing a bounded helper AND everything it spawned. #498.
///
/// `lifecycle::output_within` promises two things: it returns inside its
/// budget, and it does not orphan what it killed. Both need a way to address a
/// process TREE, and the two platforms have nothing in common there:
///
/// * **Unix** — the child is spawned into its own process group with
///   `process_group(0)`, and one `killpg` takes the group. See
///   [`force_kill_group`] for what it cost when only the direct child was
///   signalled.
/// * **Windows** — there are no process groups. A Job Object is created,
///   the child is assigned to it, and `TerminateJobObject` takes every
///   process in the job, at any depth. This is the implementation the module
///   header has promised since the Unix side was written, and #419 wants the
///   same primitive for the long-running server child.
///
/// Before this, the non-Windows arm of [`force_kill_group`] returned `false`
/// and `output_within` fell back to killing the direct child alone — so a
/// grandchild holding the inherited pipes kept the drain threads from ever
/// seeing EOF, and the "bounded" helper blocked for as long as it lived. The
/// bound was not a bound (#498).
pub struct TreeKiller {
    #[cfg(windows)]
    job: windows_sys::Win32::Foundation::HANDLE,
}

#[cfg(unix)]
impl TreeKiller {
    /// Nothing to allocate: the group is established by the spawn itself.
    pub fn new() -> Self {
        Self {}
    }

    /// The group is set via `process_group(0)` at spawn, so there is nothing
    /// to adopt after the fact. Always succeeds.
    pub fn adopt(&self, _child: &std::process::Child) -> bool {
        true
    }

    pub fn kill_tree(&self, child: &std::process::Child) -> bool {
        force_kill_group(child.id())
    }
}

#[cfg(windows)]
impl TreeKiller {
    pub fn new() -> Self {
        // SAFETY: null name and null security attributes are the documented
        // way to create an unnamed, non-inheritable job object.
        let job = unsafe {
            windows_sys::Win32::System::JobObjects::CreateJobObjectW(
                std::ptr::null(),
                std::ptr::null(),
            )
        };
        Self { job }
    }

    /// Put `child` in the job.
    ///
    /// **The assignment race is real and is not closed here.** A process
    /// created and then assigned can, in principle, spawn a descendant in the
    /// window between the two, and that descendant is never in the job. The
    /// airtight form is `CREATE_SUSPENDED` -> assign -> `ResumeThread`, which
    /// `std::process::Command` cannot express: it does not hand back the
    /// primary thread handle, so there is nothing to resume without
    /// enumerating threads by hand. The window is microseconds and the
    /// helpers this runs (`codesign`, `ps`) spawn nothing at all, so the
    /// trade is taken deliberately rather than overlooked. Revisit with
    /// #419, which needs the same primitive for a child that DOES spawn.
    pub fn adopt(&self, child: &std::process::Child) -> bool {
        use std::os::windows::io::AsRawHandle;
        if self.job.is_null() {
            return false;
        }
        // SAFETY: `job` came from CreateJobObjectW above and the handle is
        // owned by the live `child`, so both are valid for this call.
        let assigned = unsafe {
            windows_sys::Win32::System::JobObjects::AssignProcessToJobObject(
                self.job,
                child.as_raw_handle() as windows_sys::Win32::Foundation::HANDLE,
            )
        };
        assigned != 0
    }

    pub fn kill_tree(&self, _child: &std::process::Child) -> bool {
        if self.job.is_null() {
            return false;
        }
        // SAFETY: `job` is the handle created above; exit code 1 marks a
        // forced termination.
        let terminated =
            unsafe { windows_sys::Win32::System::JobObjects::TerminateJobObject(self.job, 1) };
        terminated != 0
    }
}

#[cfg(windows)]
impl Drop for TreeKiller {
    fn drop(&mut self) {
        if !self.job.is_null() {
            // SAFETY: the handle is ours and is dropped exactly once.
            //
            // The job is created WITHOUT `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`
            // on purpose: closing it must dissolve the job, not kill whatever
            // is still in it. That keeps the success path identical to Unix,
            // where a helper that exits normally leaves its descendants alone
            // and only the TIMEOUT path takes the tree.
            unsafe {
                windows_sys::Win32::Foundation::CloseHandle(self.job);
            }
        }
    }
}

/// Forcibly kill ONE process that is not our direct child. #499.
///
/// `Child::kill()` only works on a `Child` handle this process owns. A
/// `setsid()`-detached descendant is not one: it left the process group, so
/// [`force_kill_group`] cannot see it either, and the supervisor only knows
/// its PID from a `ps` walk. Callers MUST verify process identity first (see
/// `lifecycle::sweep_detached`) — a bare PID is not proof it is still the
/// process we meant.
#[cfg(unix)]
pub fn force_kill_pid(pid: u32) -> bool {
    let Ok(pid) = i32::try_from(pid) else {
        return false;
    };
    // SAFETY: pid is caller-verified as the same process it observed; SIGKILL.
    (unsafe { libc::kill(pid, libc::SIGKILL) }) == 0
}

#[cfg(not(unix))]
pub fn force_kill_pid(_pid: u32) -> bool {
    false
}

/// Does this process group still have any member? #467.
///
/// Signal 0 performs the permission and existence checks without delivering
/// anything, which is the portable way to ask.
///
/// **This is also what makes the post-reap sweep safe from PID reuse.** A
/// process-group lifetime ends only when its LAST member leaves, and a PID
/// cannot be recycled while it is still in use as a PGID. So if this returns
/// true after the direct child has been reaped, the group is still the one we
/// created — not an unrelated process that inherited a recycled number.
#[cfg(unix)]
pub fn group_has_members(pgid: u32) -> bool {
    let Ok(pgid) = i32::try_from(pgid) else {
        return false;
    };
    // SAFETY: signal 0 delivers nothing; it only reports whether the group
    // exists and is signallable by this process.
    (unsafe { libc::killpg(pgid, 0) }) == 0
}

#[cfg(not(unix))]
pub fn group_has_members(_pgid: u32) -> bool {
    false
}

/// Forcibly kill a bounded helper subprocess AND anything it spawned. #497.
///
/// `lifecycle::output_within` puts these children in their own process group
/// precisely so this call can reach a GRANDCHILD. Killing only the direct
/// child is not enough, and the difference is not theoretical: a shell that
/// forks rather than execs leaves its grandchild holding the inherited stdout
/// and stderr pipes, so the reader threads never see EOF and the "bounded"
/// helper blocks for as long as the grandchild lives. Measured while building
/// #497: a 300 ms budget took 30.007 s.
///
/// Windows needs the Job Object this module's header already anticipates;
/// until then the non-unix arm returns false and the caller falls back to
/// killing the direct child alone.
#[cfg(unix)]
pub fn force_kill_group(pgid: u32) -> bool {
    let Ok(pgid) = i32::try_from(pgid) else {
        return false;
    };
    // SAFETY: pgid is the group `output_within` created with
    // `process_group(0)`, which makes it equal to that direct child's PID.
    // SIGKILL only, and only to a group this process created.
    (unsafe { libc::killpg(pgid, libc::SIGKILL) }) == 0
}

#[cfg(not(unix))]
pub fn force_kill_group(_pgid: u32) -> bool {
    false
}

#[allow(dead_code)]
#[cfg(not(unix))]
pub fn request_terminate(_pid: u32) -> bool {
    // No cooperative-terminate primitive is wired for this platform yet;
    // the caller escalates to the portable forced kill.
    false
}
