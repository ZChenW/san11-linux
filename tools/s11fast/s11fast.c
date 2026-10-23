// s11fast.dll: make SIRE's WriteProcessMemory cheap under Wine.
// Wine's WriteProcessMemory asks the target process for the page protection first (VirtualQueryEx). Across
// processes that is a round trip through the target (~65 us), four times the cost of the write itself, and
// SIRE writes ~50,000 times while the game shows its title. Writable pages need no protection change, so
// write first and leave anything else (read-only code pages) to the original function.
// Loaded into SIRE by s11inject.exe; it redirects the import slots that hold WriteProcessMemory.
#include <windows.h>

typedef LONG (WINAPI *nt_write_t)(HANDLE, void *, const void *, SIZE_T, SIZE_T *);
typedef BOOL (WINAPI *write_t)(HANDLE, void *, const void *, SIZE_T, SIZE_T *);

static nt_write_t nt_write;
static write_t slow_write;

// Optional timing log (S11FAST_LOG=<windows path>): one line per run of writes less than 0.5 s apart,
// "<unix start> <unix end> <writes> <fallbacks>".
static HANDLE log_file = INVALID_HANDLE_VALUE;
static CRITICAL_SECTION log_lock;
static double run_start, run_end;
static unsigned long run_writes, run_fallbacks;

static double unix_now(void)
{
    FILETIME ft;
    GetSystemTimePreciseAsFileTime(&ft);
    return (double)(((ULONGLONG)ft.dwHighDateTime << 32 | ft.dwLowDateTime) - 116444736000000000ULL) / 1e7;
}

static void put_time(char *out, double t)
{
    unsigned long s = (unsigned long)t;
    wsprintfA(out, "%lu.%03lu", s, (unsigned long)((t - s) * 1000));
}

// Caller holds log_lock.
static void flush_run(void)
{
    char a[24], b[24], line[96];
    DWORD done;
    if (!run_writes) return;
    put_time(a, run_start);
    put_time(b, run_end);
    WriteFile(log_file, line, (DWORD)wsprintfA(line, "%s %s %lu %lu\r\n", a, b, run_writes, run_fallbacks),
              &done, NULL);
    run_writes = run_fallbacks = 0;
}

static void note(BOOL fallback)
{
    double now;
    if (log_file == INVALID_HANDLE_VALUE) return;
    now = unix_now();
    EnterCriticalSection(&log_lock);
    if (run_writes && now - run_end > 0.5) flush_run();
    if (!run_writes) run_start = now;
    run_end = now;
    run_writes++;
    run_fallbacks += fallback;
    LeaveCriticalSection(&log_lock);
}

// Writes out the last run once SIRE goes quiet.
static DWORD WINAPI log_flusher(void *unused)
{
    (void)unused;
    for (;;)
    {
        Sleep(1000);
        EnterCriticalSection(&log_lock);
        if (run_writes && unix_now() - run_end > 0.5) flush_run();
        LeaveCriticalSection(&log_lock);
    }
}

static BOOL WINAPI fast_write(HANDLE process, void *addr, const void *buffer, SIZE_T size, SIZE_T *written)
{
    SIZE_T done = 0;
    if (!nt_write(process, addr, buffer, size, &done) && done == size)
    {
        FlushInstructionCache(process, addr, size);
        note(FALSE);
        if (written) *written = done;
        return TRUE;
    }
    note(TRUE);
    return slow_write(process, addr, buffer, size, written);
}

// Window properties keyed by an atom. Wine keeps properties in the wineserver, so each GetPropW is a round trip
// (~7 us, more while the game keeps the server busy). Delphi's VCL calls GetPropW(hwnd, ControlAtom) for every
// message it routes, ~330,000 times in SIRE. Cache atom-keyed values; SIRE's own SetPropW/RemovePropW keep the
// cache current, and a hit is only used while the window still exists.
typedef HANDLE (WINAPI *get_prop_t)(HWND, LPCWSTR);
typedef BOOL (WINAPI *set_prop_t)(HWND, LPCWSTR, HANDLE);
typedef HANDLE (WINAPI *remove_prop_t)(HWND, LPCWSTR);
static get_prop_t real_get_prop;
static set_prop_t real_set_prop;
static remove_prop_t real_remove_prop;

#define PROPS 4096  // power of two, far above SIRE's ~500 windows
static struct prop { HWND hwnd; ATOM atom; BOOL used; HANDLE value; } props[PROPS];
static CRITICAL_SECTION prop_lock;

static BOOL is_atom(LPCWSTR key) { return !((ULONG_PTR)key >> 16); }

// Caller holds prop_lock. Returns the slot for (hwnd, atom), or the empty slot where it belongs.
static struct prop *prop_slot(HWND hwnd, ATOM atom)
{
    unsigned i = ((unsigned)(ULONG_PTR)hwnd * 2654435761u ^ atom) & (PROPS - 1);
    for (unsigned n = 0; n < PROPS; n++, i = (i + 1) & (PROPS - 1))
        if (!props[i].used || (props[i].hwnd == hwnd && props[i].atom == atom)) return &props[i];
    return NULL;
}

static void prop_forget(HWND hwnd, ATOM atom)
{
    struct prop *p = prop_slot(hwnd, atom);
    if (!p || !p->used) return;
    // Re-insert the rest of the cluster so linear probing still finds it.
    unsigned i = (unsigned)(p - props);
    p->used = FALSE;
    for (unsigned j = (i + 1) & (PROPS - 1); props[j].used; j = (j + 1) & (PROPS - 1))
    {
        struct prop moved = props[j];
        props[j].used = FALSE;
        *prop_slot(moved.hwnd, moved.atom) = moved;
    }
}

static void prop_store(HWND hwnd, ATOM atom, HANDLE value)
{
    struct prop *p = prop_slot(hwnd, atom);
    if (p) *p = (struct prop){ hwnd, atom, TRUE, value };
}

static BOOL own_window(HWND hwnd)
{
    DWORD pid = 0;
    return GetWindowThreadProcessId(hwnd, &pid) && pid == GetCurrentProcessId();
}

static HANDLE WINAPI cached_get_prop(HWND hwnd, LPCWSTR key)
{
    HANDLE value;
    if (!is_atom(key) || !own_window(hwnd)) return real_get_prop(hwnd, key);
    EnterCriticalSection(&prop_lock);
    struct prop *p = prop_slot(hwnd, (ATOM)(ULONG_PTR)key);
    if (p && p->used)
    {
        if (IsWindow(hwnd))
        {
            value = p->value;
            LeaveCriticalSection(&prop_lock);
            return value;
        }
        prop_forget(hwnd, (ATOM)(ULONG_PTR)key);
    }
    value = real_get_prop(hwnd, key);
    prop_store(hwnd, (ATOM)(ULONG_PTR)key, value);
    LeaveCriticalSection(&prop_lock);
    return value;
}

static BOOL WINAPI cached_set_prop(HWND hwnd, LPCWSTR key, HANDLE value)
{
    BOOL ok;
    if (!is_atom(key)) return real_set_prop(hwnd, key, value);
    EnterCriticalSection(&prop_lock);
    prop_forget(hwnd, (ATOM)(ULONG_PTR)key);
    ok = real_set_prop(hwnd, key, value);
    LeaveCriticalSection(&prop_lock);
    return ok;
}

static HANDLE WINAPI cached_remove_prop(HWND hwnd, LPCWSTR key)
{
    HANDLE value;
    if (!is_atom(key)) return real_remove_prop(hwnd, key);
    EnterCriticalSection(&prop_lock);
    prop_forget(hwnd, (ATOM)(ULONG_PTR)key);
    value = real_remove_prop(hwnd, key);
    LeaveCriticalSection(&prop_lock);
    return value;
}

// Global atoms live in the wineserver too. Delphi's FindControl checks GlobalFindAtomW(ControlAtomString) before
// each GetPropW, so the lookups come in the same numbers. Cache found names; any GlobalAddAtomW or
// GlobalDeleteAtom from SIRE empties the cache. The names are SIRE's own (they embed its instance and thread).
typedef ATOM (WINAPI *find_atom_t)(LPCWSTR);
typedef ATOM (WINAPI *add_atom_t)(LPCWSTR);
typedef ATOM (WINAPI *delete_atom_t)(ATOM);
static find_atom_t real_find_atom;
static add_atom_t real_add_atom;
static delete_atom_t real_delete_atom;

#define ATOMS 16
static struct { WCHAR name[64]; ATOM atom; } atoms[ATOMS];
static int atom_count;

// Code-unit equality. lstrcmpW compares by locale and cost more under Wine than the lookup it saves; a stricter
// match can only miss the cache, which falls through to the real lookup.
static BOOL same_name(LPCWSTR a, LPCWSTR b)
{
    while (*a && *a == *b) a++, b++;
    return *a == *b;
}

static ATOM WINAPI cached_find_atom(LPCWSTR name)
{
    ATOM atom;
    if (is_atom(name) || lstrlenW(name) >= 64) return real_find_atom(name);
    EnterCriticalSection(&prop_lock);
    for (int i = 0; i < atom_count; i++)
    {
        if (!same_name(atoms[i].name, name)) continue;
        atom = atoms[i].atom;
        LeaveCriticalSection(&prop_lock);
        return atom;
    }
    atom = real_find_atom(name);
    if (atom && atom_count < ATOMS)
    {
        lstrcpyW(atoms[atom_count].name, name);
        atoms[atom_count++].atom = atom;
    }
    LeaveCriticalSection(&prop_lock);
    return atom;
}

static ATOM WINAPI cached_add_atom(LPCWSTR name)
{
    ATOM atom;
    EnterCriticalSection(&prop_lock);
    atom_count = 0;
    atom = real_add_atom(name);
    LeaveCriticalSection(&prop_lock);
    return atom;
}

static ATOM WINAPI cached_delete_atom(ATOM atom)
{
    ATOM result;
    EnterCriticalSection(&prop_lock);
    atom_count = 0;
    result = real_delete_atom(atom);
    LeaveCriticalSection(&prop_lock);
    return result;
}

// Point every import slot holding one of from[i] at to[i] (to == NULL only counts). Matching by address needs
// neither the DLL name nor a name table, and works for imports bound through kernel32/user32 forwarders.
static int redirect(HMODULE module, const ULONG_PTR *from, const ULONG_PTR *to, int pairs)
{
    BYTE *base = (BYTE *)module;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    int count = 0;
    if (!dir.VirtualAddress) return 0;
    for (IMAGE_IMPORT_DESCRIPTOR *d = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir.VirtualAddress); d->Name; d++)
    {
        for (IMAGE_THUNK_DATA *slot = (IMAGE_THUNK_DATA *)(base + d->FirstThunk); slot->u1.Function; slot++)
        {
            for (int i = 0; i < pairs; i++)
            {
                DWORD old;
                if (!from[i] || slot->u1.Function != from[i]) continue;
                if (!to) { count++; break; }
                if (!VirtualProtect(&slot->u1.Function, sizeof(slot->u1.Function), PAGE_READWRITE, &old)) break;
                slot->u1.Function = to[i];
                VirtualProtect(&slot->u1.Function, sizeof(slot->u1.Function), old, &old);
                count++;
                break;
            }
        }
    }
    return count;
}

// Redirect a group of imports only if every member is imported: a cache stays exact only while all the calls
// that change what it holds (SetPropW, RemovePropW, GlobalAddAtomW, GlobalDeleteAtom) pass through it.
static int redirect_group(HMODULE exe, const ULONG_PTR *from, const ULONG_PTR *to, int pairs)
{
    for (int i = 0; i < pairs; i++)
        if (!from[i] || !redirect(exe, &from[i], NULL, 1)) return 0;
    return redirect(exe, from, to, pairs);
}

// Called by s11inject.exe through CreateRemoteThread after the DLL is loaded; returns the number of slots.
__declspec(dllexport) DWORD WINAPI s11fast_install(void *unused)
{
    wchar_t path[MAX_PATH];
    HMODULE user32 = GetModuleHandleA("user32.dll"), kernel32 = GetModuleHandleA("kernel32.dll");
    HMODULE exe = GetModuleHandleW(NULL);
    (void)unused;
    nt_write = (nt_write_t)GetProcAddress(GetModuleHandleA("ntdll.dll"), "NtWriteVirtualMemory");
    slow_write = (write_t)GetProcAddress(kernel32, "WriteProcessMemory");
    real_get_prop = (get_prop_t)GetProcAddress(user32, "GetPropW");
    real_set_prop = (set_prop_t)GetProcAddress(user32, "SetPropW");
    real_remove_prop = (remove_prop_t)GetProcAddress(user32, "RemovePropW");
    real_find_atom = (find_atom_t)GetProcAddress(kernel32, "GlobalFindAtomW");
    real_add_atom = (add_atom_t)GetProcAddress(kernel32, "GlobalAddAtomW");
    real_delete_atom = (delete_atom_t)GetProcAddress(kernel32, "GlobalDeleteAtom");
    if (GetEnvironmentVariableW(L"S11FAST_LOG", path, MAX_PATH) - 1 < MAX_PATH - 1)
    {
        InitializeCriticalSection(&log_lock);
        log_file = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ, NULL, OPEN_ALWAYS, 0, NULL);
        if (log_file != INVALID_HANDLE_VALUE) CloseHandle(CreateThread(NULL, 0, log_flusher, NULL, 0, NULL));
    }
    InitializeCriticalSection(&prop_lock);

    const ULONG_PTR write_from[] = { (ULONG_PTR)slow_write }, write_to[] = { (ULONG_PTR)fast_write };
    const ULONG_PTR prop_from[] = { (ULONG_PTR)real_set_prop, (ULONG_PTR)real_remove_prop, (ULONG_PTR)real_get_prop };
    const ULONG_PTR prop_to[] = { (ULONG_PTR)cached_set_prop, (ULONG_PTR)cached_remove_prop,
                                  (ULONG_PTR)cached_get_prop };
    const ULONG_PTR atom_from[] = { (ULONG_PTR)real_add_atom, (ULONG_PTR)real_delete_atom,
                                    (ULONG_PTR)real_find_atom };
    const ULONG_PTR atom_to[] = { (ULONG_PTR)cached_add_atom, (ULONG_PTR)cached_delete_atom,
                                  (ULONG_PTR)cached_find_atom };
    int slots = nt_write ? redirect_group(exe, write_from, write_to, 1) : 0;
    slots += redirect_group(exe, prop_from, prop_to, 3);
    slots += redirect_group(exe, atom_from, atom_to, 3);
    return (DWORD)slots;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, void *reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(instance);
    return TRUE;
}
