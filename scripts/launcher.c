/*
 * VDX OpenAgent.app launcher (compiled by scripts/install.sh).
 *
 * The app's main executable must be a real binary that *spawns* Python as a
 * child, not a shell script that execs it: macOS privacy permissions
 * (microphone, …) are granted to the "responsible" process. With exec, that is
 * the Python binary, which has no NSMicrophoneUsageDescription, so macOS denies
 * the mic silently and never lists the app. With spawn, the responsible process
 * stays this signed app bundle, whose Info.plist carries the description.
 *
 * It runs Contents/Resources/launch.sh, forwards quit signals and exits with
 * the child's status.
 */
#include <errno.h>
#include <libgen.h>
#include <limits.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif

extern char **environ;
static pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(void) {
    char exe[PATH_MAX], real[PATH_MAX], script[PATH_MAX];
#ifdef __APPLE__
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0) return 1;
#else
    ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n < 0) return 1;
    exe[n] = '\0';
#endif
    if (!realpath(exe, real)) return 1;
    /* .../VDX OpenAgent.app/Contents/MacOS/VDX OpenAgent -> .../Contents/Resources/launch.sh */
    snprintf(script, sizeof script, "%s/../Resources/launch.sh", dirname(real));

    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);

    char *argv[] = {"/bin/bash", script, NULL};
    if (posix_spawn(&child, "/bin/bash", NULL, NULL, argv, environ) != 0) {
        perror("VDX OpenAgent: cannot start launch.sh");
        return 1;
    }
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) return 1; /* EINTR: a forwarded signal; keep waiting for the child */
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
