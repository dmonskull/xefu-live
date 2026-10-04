# Modding original Xbox games on the 360 from your own code

Two small layers that let you read and write an original Xbox game's memory
while it runs on an Xbox 360, using the game's own addresses (the ones Ghidra
or IDA show for the XBE):

- `csharp/` for PC tools. The connection and XDRPC side follows
  [DMONET](https://github.com/dmonskull/DMONET3) (XDevkit + XDRPC), and there
  is a plain XBDM option that needs no DLLs.
- `cpp360/` for code that runs on the console (plugins, trainers)

Plus a template for each.

## Why you need a layer at all

An original Xbox game on a 360 runs inside the emulator (xefu). Its memory is
not where the game thinks it is, and it is the other byte order:

- The emulator keeps the Xbox's 64 MB of RAM as one block of 360 memory
  (at 0xD0000000 on xefu7).
- It runs a real x86 Xbox kernel in that RAM, so a game address has to go
  through the game's x86 page tables to find the 360 address behind it.
- Everything in the game is little endian. The 360 and the usual 360 tools
  are big endian, so `console.ReadUInt32` or a plain `*(DWORD*)` on game data
  gives you the bytes backwards.

Both layers do the lookup and the byte order for you. You pass a game address,
you get the right value.

Two things they cannot do:

- Change code that already ran. The emulator translates x86 to PowerPC and
  keeps the translation, so patching an instruction the game already executed
  does nothing. Data changes work straight away.
- Tell you the addresses. Find those with [Xefu Live](../README.md) or a
  disassembler.

## C#

Copy the `csharp/OgXbox` folder into your project (plain .cs files, nothing to
install), plus `csharp/XDevkit` if your tool talks to the console through
XDevkit like DMONET does.

### In a DMONET style tool

DMONET keeps one console object, `Form1.xbCon`, and every form uses it through
the `XDRPCPlusPlus` helpers (`xbCon.ReadBytes`, `xbCon.WriteFloat`, ...). Those
write big endian values to 360 addresses, which is right for 360 games and
wrong for an Xbox game inside the emulator. `OgXboxExtensions.cs` adds one
method next to them:

    using OgXbox;

    // the game's own address, the game's own byte order
    Form1.xbCon.OgXbox().WriteFloat(0x00BB85B8, 999f);
    float health = Form1.xbCon.OgXbox().ReadFloat(0x00BB85B8);

`OgXbox()` finds the game the first time, keeps it, and looks again if the
player quits or starts another game. It throws `XboxGameException` when no
original Xbox game is running. The object it returns also tells you what is
running:

    XboxGame game = Form1.xbCon.OgXbox();
    // game.TitleName, game.TitleId (the Xbox game's own ID), game.Emulator

To use it in DMONET itself, add the files from `csharp/OgXbox` (except
`XbdmSocket.cs`, unless you want it) and `XDevkitHost.cs` and
`OgXboxExtensions.cs` from `csharp/XDevkit` to the project.

### In a new tool

`XboxConnection.cs` is DMONET's connect code on its own (XboxManager, default
console from Neighborhood, connect as debugger):

    if (XboxConnection.ConnectToConsole())
    {
        XboxGame game = XboxConnection.xbCon.OgXbox();
        game.WriteFloat(0x00BB85B8, 999f);
    }

XDRPC is not needed for reading and writing, that goes through XDevkit's
debug target and only needs xbdm on the console. XDRPC still works for system
calls (`xbCon.GetCurrentTitleId()` returns FFFE07D2 for every Xbox game, that
is the emulator). It cannot call the Xbox game's own functions: those are x86
code inside the emulator, not 360 code.

### Without XDevkit

Straight over XBDM, nothing installed (works on Mac and Linux too):

    using (XbdmSocket xbdm = new XbdmSocket("192.168.1.50"))
    {
        XboxGame game = new XboxGame(xbdm);
        if (game.Attach()) game.WriteFloat(0x00BB85B8, 999f);
    }

Anything else that can read and write 360 memory fits in two lambdas:

    new XboxGame(new DelegateHost((addr, len) => MyRead(addr, len), (addr, data) => MyWrite(addr, data)));

### What XboxGame gives you

    Attach() / StillRunning()             find the running game / check it is still there
    TitleId, TitleName, Emulator          what is running
    Sections                              the game's XBE sections
    ReadByte / ReadInt16 / ReadUInt16 / ReadInt32 / ReadUInt32
    ReadFloat / ReadDouble / ReadBool / ReadString / ReadUnicodeString / ReadBytes
    Write...                              the same set
    Follow(address, 0x10, 0x4)            pointer chain: [[address] + 0x10] + 0x4
    ToHost(address)                       the real 360 address, for other tools

`Freezer` keeps values pinned, for infinite health and the like:

    Freezer freezer = new Freezer(game);
    freezer.SetFloat(0x00BB85B8, 999f);
    freezer.Apply();        // call this from a WinForms timer

With XDevkit call `Apply()` from a WinForms timer rather than a background
thread. XDevkit is COM and should stay on the thread that created it.

### The templates

`csharp/TrainerTemplate` is a WinForms trainer built the DMONET way: connect
button, a tick list of cheats for the game that is running, and a peek/poke
row. Your cheats go in `Cheats.cs`, one list per title ID. It includes
DMONET's `XDRPCPlusPlus.cs` for the XDRPC helpers. Put `xdevkit.dll` and
`xdrpc.dll` in its `libs` folder (not included) and build as x86.

`csharp/ConsoleExample` is the smallest working tool, over plain XBDM:

    cd csharp/ConsoleExample
    dotnet run -- 192.168.1.50
    dotnet run -- 192.168.1.50 peek BB85B8 float
    dotnet run -- 192.168.1.50 poke BB85B8 float 999

## C++ on the console

`cpp360/ogxbox.h` is one header with no dependencies beyond `MmIsAddressValid`.
Include your kernel header first, then:

    #include "ogxbox.h"

    if (XamGetCurrentTitleId() == ogx::kEmuTitleId && ogx::Attach())
    {
        if (ogx::TitleId() == 0x4D57000E)               // which Xbox game it is
            ogx::WriteFloat(0x00BB85B8, 999.0f);
    }

What is in it:

    ogx::Attach() / Attached() / StillRunning() / Detach()
    ogx::TitleId(), ogx::TitleName(buffer, chars)       the Xbox game, from its XBE
    ogx::ReadU8 / ReadU16 / ReadU32 / ReadS16 / ReadS32 / ReadFloat / ReadBool / ReadString
    ogx::Write...                                       the same set, false if not mapped
    ogx::Read(address, buffer, size) / Write(...)       raw bytes
    ogx::Follow(address, offsets, count)                pointer chain
    ogx::Ptr(address)                                   pointer into 360 memory, NULL if not mapped
    ogx::Mapped(address, size)

`XamGetCurrentTitleId()` returns 0xFFFE07D2 for every original Xbox game, that
is the emulator. `ogx::TitleId()` is the game's own ID.

Call `ogx::StillRunning()` before you touch memory in a loop. The RAM block
goes away when the player quits the game.

### The trainer template

`cpp360/TrainerTemplate` is a Dashlaunch plugin. It waits for an Xbox game,
looks up its cheats in `games.cpp` and runs the ones that are switched on.
Hold the left stick click and press D-pad down/up to pick a cheat, D-pad right
to switch it. It shows what it is doing with notifications, there is no drawn
menu.

To build it you need Visual Studio 2010 with the Xbox 360 SDK, and xkelib for
the kernel exports. Set an `XKELIB` environment variable to the folder with
`xkelib.h` and `xkelib.lib`, open `TrainerTemplate.vcxproj`, build Release.
Then add the .xex as a plugin in launch.ini.

`cpp360/test/selftest.cpp` checks the header on a PC with a fake RAM image:

    c++ -I cpp360 cpp360/test/selftest.cpp -o selftest && ./selftest

## What has been tested

- C# layer: against a real console (JTAG, xefu7, Gauntlet Dark Legacy) through
  the plain XBDM transport. The XDevkit pieces and the WinForms template
  compile, but have not been run against the real xdevkit.dll and xdrpc.dll yet.
- C++ header: on a PC, against RAM dumps taken from the same console.
- C++ plugin template: not built with the SDK or run on a console yet. Treat
  it as a starting point.
- Only xefu7 has been checked. Other emulator builds are recognised and the
  RAM block is searched for, but that path is unproven.
