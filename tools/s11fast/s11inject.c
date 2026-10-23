// s11inject.exe <program> [args...]: start a program in its own directory, load s11fast.dll (next to this exe)
// into it once its UI is idle, run s11fast_install there, then wait for the program and return its exit code.
// Any failure leaves the program running unchanged. Built for the GUI subsystem so no console window opens;
// messages go to OutputDebugString (Proton's log records them with +debugstr, which `san11 run` enables).
#include <windows.h>
#include <shellapi.h>
#include <stdarg.h>
#include <wchar.h>

static void say(const char *format, ...)
{
    char line[512];
    va_list args;
    va_start(args, format);
    wvsprintfA(line, format, args);
    va_end(args);
    OutputDebugStringA(line);
}

static DWORD run_remote(HANDLE process, void *start, void *arg)
{
    DWORD code = 0;
    HANDLE thread = CreateRemoteThread(process, NULL, 0, (LPTHREAD_START_ROUTINE)start, arg, 0, NULL);
    if (!thread) return 0;
    WaitForSingleObject(thread, 30000);
    GetExitCodeThread(thread, &code);
    CloseHandle(thread);
    return code;
}

static void install(HANDLE process)
{
    wchar_t dll[MAX_PATH];
    DWORD len = GetModuleFileNameW(NULL, dll, MAX_PATH);
    wchar_t *slash = wcsrchr(dll, L'\\');
    if (!len || !slash || (size_t)(slash - dll) + 13 >= MAX_PATH) return;
    wcscpy(slash + 1, L"s11fast.dll");

    // The remote export address is the remote base plus the export's offset in a local copy.
    HMODULE local = LoadLibraryW(dll);
    FARPROC entry = local ? GetProcAddress(local, "s11fast_install") : NULL;
    if (local && !entry) entry = GetProcAddress(local, "s11fast_install@4");
    if (!entry) { say("s11fast: cannot load %ls\n", dll); return; }

    SIZE_T bytes = (wcslen(dll) + 1) * sizeof(wchar_t);
    void *remote_path = VirtualAllocEx(process, NULL, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remote_path || !WriteProcessMemory(process, remote_path, dll, bytes, NULL)) return;
    // kernel32 sits at the same address in every process of this prefix.
    DWORD base = run_remote(process, (void *)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "LoadLibraryW"),
                            remote_path);
    VirtualFreeEx(process, remote_path, 0, MEM_RELEASE);
    if (!base) { say("s11fast: LoadLibraryW failed in the target\n"); return; }
    DWORD slots = run_remote(process, (BYTE *)(ULONG_PTR)base + ((BYTE *)entry - (BYTE *)local), NULL);
    say("s11fast: %lu import slot(s) redirected\n", (unsigned long)slots);
}

int main(void)
{
    int argc;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argc < 2) { say("usage: s11inject <program> [args...]\n"); return 2; }

    wchar_t cmdline[4096] = L"", dir[MAX_PATH];
    for (int i = 1; i < argc; i++)
    {
        if (wcslen(cmdline) + wcslen(argv[i]) + 4 >= 4096) return 2;
        if (i > 1) wcscat(cmdline, L" ");
        wcscat(cmdline, L"\"");
        wcscat(cmdline, argv[i]);
        wcscat(cmdline, L"\"");
    }
    wcsncpy(dir, argv[1], MAX_PATH - 1);
    dir[MAX_PATH - 1] = 0;
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;

    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi;
    if (!CreateProcessW(argv[1], cmdline, NULL, NULL, FALSE, 0, NULL, slash ? dir : NULL, &si, &pi))
    {
        say("s11inject: cannot start %ls (error %lu)\n", argv[1], (unsigned long)GetLastError());
        return 1;
    }
    WaitForInputIdle(pi.hProcess, 60000);
    install(pi.hProcess);

    DWORD code = 1;
    WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, &code);
    return (int)code;
}
