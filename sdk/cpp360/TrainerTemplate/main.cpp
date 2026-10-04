// Trainer plugin for original Xbox games running on the 360.
//
// Load it as a Dashlaunch plugin. It waits for an Xbox game to start, works out
// which one it is, and runs the cheats from games.cpp.
//
// Controls (hold the left stick click):
//   + D-pad down / up   next / previous cheat
//   + D-pad right       switch it on or off
//
// The menu is just notifications. Drawing a real one would mean hooking the
// emulator's renderer, which this template does not try to do.

#include "stdafx.h"
#include "games.h"

static volatile bool g_unload = false;

static void Notify(const wchar_t* text)
{
    // 14 is the plain message popup
    XNotifyQueueUI((XNOTIFYQUEUEUI_TYPE)14, 0, 2, (PWCHAR)text, NULL);
}

static void ShowCheat(const Cheat& cheat)
{
    wchar_t text[96];
    swprintf_s(text, 96, L"%ls: %ls", cheat.name, cheat.on ? L"ON" : L"OFF");
    Notify(text);
}

static void PollPad(Game* game, int& selected, WORD& lastButtons)
{
    XINPUT_STATE pad;
    if (XInputGetState(0, &pad) != ERROR_SUCCESS) return;
    WORD buttons = pad.Gamepad.wButtons;
    WORD pressed = buttons & ~lastButtons;
    lastButtons = buttons;
    if (!(buttons & XINPUT_GAMEPAD_LEFT_THUMB)) return;

    if (pressed & XINPUT_GAMEPAD_DPAD_DOWN)
    {
        selected = (selected + 1) % game->count;
        ShowCheat(game->cheats[selected]);
    }
    else if (pressed & XINPUT_GAMEPAD_DPAD_UP)
    {
        selected = (selected + game->count - 1) % game->count;
        ShowCheat(game->cheats[selected]);
    }
    else if (pressed & XINPUT_GAMEPAD_DPAD_RIGHT)
    {
        game->cheats[selected].on = !game->cheats[selected].on;
        ShowCheat(game->cheats[selected]);
    }
}

static DWORD WINAPI TrainerThread(LPVOID)
{
    ogx::u32 title = 0;
    Game* game = NULL;
    int selected = 0;
    WORD lastButtons = 0;

    while (!g_unload)
    {
        // every original Xbox game runs under the emulator's own title ID
        if (XamGetCurrentTitleId() != ogx::kEmuTitleId)
        {
            ogx::Detach();
            title = 0;
            game = NULL;
            Sleep(1000);
            continue;
        }
        // the game's RAM moves or goes away when the player quits, so keep checking
        if (!ogx::StillRunning() && !ogx::Attach())
        {
            title = 0;
            game = NULL;
            Sleep(500);
            continue;
        }

        ogx::u32 now = ogx::TitleId();
        if (now == 0)
        {
            Sleep(250);         // the emulator is up but the game has not loaded yet
            continue;
        }
        if (now != title)
        {
            title = now;
            game = FindGame(title);
            selected = 0;
            if (game)
            {
                for (int i = 0; i < game->count; i++) game->cheats[i].on = false;
                wchar_t text[96];
                swprintf_s(text, 96, L"Trainer ready: %ls", game->name);
                Notify(text);
            }
        }

        if (game)
        {
            PollPad(game, selected, lastButtons);
            for (int i = 0; i < game->count; i++)
                if (game->cheats[i].on) game->cheats[i].apply();
        }
        Sleep(50);
    }
    return 0;
}

BOOL APIENTRY DllMain(HANDLE module, DWORD reason, LPVOID reserved)
{
    if (reason == DLL_PROCESS_ATTACH)
    {
        // flag 2 makes it a system thread, so it keeps running when the title changes
        HANDLE thread;
        DWORD id;
        ExCreateThread(&thread, 0, &id, (PVOID)XapiThreadStartup,
                       (LPTHREAD_START_ROUTINE)TrainerThread, NULL, 0x2 | CREATE_SUSPENDED);
        XSetThreadProcessor(thread, 4);
        ResumeThread(thread);
        CloseHandle(thread);
    }
    else if (reason == DLL_PROCESS_DETACH)
    {
        g_unload = true;
        Sleep(200);
    }
    return TRUE;
}
