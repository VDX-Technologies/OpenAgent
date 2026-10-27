/*
 * VDX OpenAgent.app launcher (compiled by scripts/install.sh).
 *
 * macOS identifies an app by the executable its process runs. If the bundle
 * just exec'd the project's Python, the running process would be Python: the
 * Dock shows "Python" with its rocket icon, and microphone access is denied
 * silently because Python's Info.plist has no NSMicrophoneUsageDescription.
 *
 * So install.sh copies the Python interpreter into the bundle
 * (Contents/MacOS/vdx-python), and this launcher execs that copy in the same
 * process. The process then belongs to VDX OpenAgent.app: its name and icon in
 * the Dock, and its privacy permissions (the microphone prompt).
 *
 * Build-time defines (paths): VDX_ROOT (project), VDX_HOME (Python's
 * base prefix), VDX_SITE (the venv's site-packages).
 */
#include <libgen.h>
#include <limits.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif

#ifndef VDX_ROOT
#error "build with -DVDX_ROOT=... -DVDX_HOME=... -DVDX_SITE=..."
#endif

extern char **environ;

/* Adds the venv's packages, then runs desktop.py as __main__. */
static const char *BOOT =
    "import os, runpy, site, sys\n"
    "os.environ.pop('PYTHONHOME', None)  # don't leak into subprocesses (git, pip, ...)\n"
    "site.addsitedir(sys.argv[1])\n"
    "sys.argv = sys.argv[2:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n";

static void run_shell(const char *cmd) {
    pid_t pid;
    char *argv[] = {"/bin/bash", "-c", (char *)cmd, NULL};
    if (posix_spawn(&pid, "/bin/bash", NULL, NULL, argv, environ) == 0) waitpid(pid, NULL, 0);
}

int main(void) {
    char exe[PATH_MAX], real[PATH_MAX], dir[PATH_MAX], python[PATH_MAX], logpath[PATH_MAX];
#ifdef __APPLE__
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0) return 1;
#else
    ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n < 0) return 1;
    exe[n] = '\0';
#endif
    if (!realpath(exe, real)) return 1;
    snprintf(dir, sizeof dir, "%s", real);
    snprintf(python, sizeof python, "%s/vdx-python", dirname(dir));

    /* Launch errors go to ~/Library/Logs/VDX.log (readable even if Desktop access is denied). */
    const char *home = getenv("HOME");
    snprintf(logpath, sizeof logpath, "%s/Library/Logs/VDX.log", home ? home : "/tmp");
    int fd = open(logpath, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd >= 0) { dup2(fd, 1); dup2(fd, 2); close(fd); }
    char stamp[64];
    time_t now = time(NULL);
    strftime(stamp, sizeof stamp, "%Y-%m-%d %H:%M:%S", localtime(&now));
    printf("--- %s launching\n", stamp);
    fflush(stdout);

    run_shell("pgrep -x ollama >/dev/null || open -ga Ollama 2>/dev/null || (nohup ollama serve >/dev/null 2>&1 &)");

    if (chdir(VDX_ROOT) != 0) {
        fprintf(stderr, "cannot access %s (grant Files & Folders access)\n", VDX_ROOT);
        return 1;
    }
    setenv("PYTHONHOME", VDX_HOME, 1);
    setenv("VDX_LAUNCHER", real, 1);  /* the updater relaunches through this */
    char *argv[] = {python, "-c", (char *)BOOT, VDX_SITE, "desktop.py", NULL};
    execv(python, argv);
    perror("VDX OpenAgent: cannot start Python");
    return 1;
}
