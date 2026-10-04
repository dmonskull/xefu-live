#include "stdafx.h"
#include "games.h"

// Addresses are the game's own, the ones Ghidra or IDA show for the XBE.
// ogx::Write* takes care of translating them and of the byte order.

// ---- Gauntlet Dark Legacy (4D57000E) ----------------------------------------
// player records are 0x6140 bytes apart, health is a float

static const ogx::u32 kGauntletHealth = 0x00BB85B8;
static const ogx::u32 kGauntletPlayerSize = 0x6140;

static void GauntletHealth1() { ogx::WriteFloat(kGauntletHealth, 999.0f); }
static void GauntletHealth2() { ogx::WriteFloat(kGauntletHealth + kGauntletPlayerSize, 999.0f); }

static Cheat g_gauntlet[] =
{
    { L"Player 1 infinite health", GauntletHealth1, false },
    { L"Player 2 infinite health", GauntletHealth2, false },
};

// ---- add your games here ----------------------------------------------------

static Game g_games[] =
{
    { 0x4D57000E, L"Gauntlet Dark Legacy", g_gauntlet, sizeof(g_gauntlet) / sizeof(g_gauntlet[0]) },
};

Game* FindGame(ogx::u32 titleId)
{
    for (size_t i = 0; i < sizeof(g_games) / sizeof(g_games[0]); i++)
        if (g_games[i].titleId == titleId) return &g_games[i];
    return NULL;
}
