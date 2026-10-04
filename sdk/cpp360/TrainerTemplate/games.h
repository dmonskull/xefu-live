#pragma once

// One cheat. While it is on, apply() runs about 20 times a second.
struct Cheat
{
    const wchar_t* name;
    void (*apply)();
    bool on;
};

struct Game
{
    ogx::u32 titleId;       // the Xbox game's own title ID, from its XBE
    const wchar_t* name;
    Cheat* cheats;
    int count;
};

// NULL if there are no cheats for that game.
Game* FindGame(ogx::u32 titleId);
