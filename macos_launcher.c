/* Native Finder entry point. The self-contained server opens the browser. */
#include <CoreFoundation/CoreFoundation.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <pwd.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

extern char **environ;

static int fail(const char *message, int error) {
    char details[1024];
    snprintf(details, sizeof(details), "%s\n%s", message, strerror(error));
    CFStringRef description = CFStringCreateWithCString(NULL, details, kCFStringEncodingUTF8);
    CFUserNotificationDisplayAlert(0, kCFUserNotificationStopAlertLevel, NULL, NULL, NULL,
        CFSTR("M4A Converter"), description, CFSTR("OK"), NULL, NULL, NULL);
    CFRelease(description);
    return 1;
}

int main(int argc, char **argv) {
    char executable[PATH_MAX], resolved[PATH_MAX], server[PATH_MAX];
    uint32_t capacity = sizeof(executable);
    if (_NSGetExecutablePath(executable, &capacity) != 0)
        return fail("Слишком длинный путь к приложению.", ENAMETOOLONG);
    if (!realpath(executable, resolved))
        return fail("Не удалось найти приложение.", errno);
    char *separator = strrchr(resolved, '/');
    if (!separator) return fail("Некорректный путь к приложению.", EINVAL);
    *separator = '\0';
    if (snprintf(server, sizeof(server), "%s/M4AConverterServer", resolved) >= (int)sizeof(server))
        return fail("Слишком длинный путь к приложению.", ENAMETOOLONG);

    const struct passwd *user = getpwuid(getuid());
    if (!user) return fail("Не удалось найти домашнюю папку.", ENOENT);
    char logs[PATH_MAX], logfile[PATH_MAX];
    if (snprintf(logs, sizeof(logs), "%s/Library/Logs/M4AConverter", user->pw_dir) >= (int)sizeof(logs))
        return fail("Слишком длинный путь к журналу.", ENAMETOOLONG);
    /* Library and Logs are standard directories, but create them if necessary. */
    for (char *part = logs + 1; *part; ++part) {
        if (*part != '/') continue;
        *part = '\0';
        int result = mkdir(logs, 0700);
        int error = errno;
        *part = '/';
        if (result != 0 && error != EEXIST)
            return fail("Не удалось создать папку журнала.", error);
    }
    if (mkdir(logs, 0700) != 0 && errno != EEXIST)
        return fail("Не удалось создать папку журнала.", errno);
    if (snprintf(logfile, sizeof(logfile), "%s/server.log", logs) >= (int)sizeof(logfile))
        return fail("Слишком длинный путь к журналу.", ENAMETOOLONG);
    int log = open(logfile, O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (log < 0) return fail("Не удалось открыть журнал запуска.", errno);
    int input = open("/dev/null", O_RDONLY);
    if (input < 0) { close(log); return fail("Не удалось подготовить запуск.", errno); }

    char **arguments = calloc((size_t)argc + 3, sizeof(char *));
    if (!arguments) { close(input); close(log); return fail("Не хватает памяти.", ENOMEM); }
    arguments[0] = "/usr/bin/nohup";
    arguments[1] = server;
    int count = 2;
    for (int index = 1; index < argc; ++index)
        if (strncmp(argv[index], "-psn_", 5) != 0) arguments[count++] = argv[index];

    posix_spawn_file_actions_t actions;
    int error = posix_spawn_file_actions_init(&actions);
    if (error == 0) {
        error = posix_spawn_file_actions_adddup2(&actions, input, STDIN_FILENO);
        if (error == 0) error = posix_spawn_file_actions_adddup2(&actions, log, STDOUT_FILENO);
        if (error == 0) error = posix_spawn_file_actions_adddup2(&actions, log, STDERR_FILENO);
        if (error == 0) error = posix_spawn_file_actions_addclose(&actions, input);
        if (error == 0) error = posix_spawn_file_actions_addclose(&actions, log);
        pid_t child;
        if (error == 0) error = posix_spawn(&child, "/usr/bin/nohup", &actions, NULL, arguments, environ);
        posix_spawn_file_actions_destroy(&actions);
    }
    free(arguments);
    close(input);
    close(log);
    if (error != 0) return fail("Не удалось запустить конвертер.", error);
    return 0;
}
