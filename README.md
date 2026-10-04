# Xefu Live

Live memory viewer/editor for **original Xbox games running on an Xbox 360**
(through the 360's built-in Xbox emulator, xefu). Works over XBDM with
[py-xbdm](https://github.com/XeCrippy/py-xbdm).

The addresses you use are the game's own addresses, the same ones Ghidra
shows when you load the game's default.xbe. No converting.

Tested on a JTAG console with Gauntlet Dark Legacy (xefu7). Other games and
emulator builds should work but I haven't tried them all.

## What you need

- A JTAG/RGH or devkit 360 with `xbdm.xex` loaded as a plugin, on your network
- An original Xbox game running on it
- Python 3.9 or newer with tkinter
- numpy and Pillow: `pip install -r requirements.txt`
- py-xbdm. The app offers to download it the first time you start it. To do
  it by hand, download it from GitHub and put the folder next to `xefulive`,
  named `py-xbdm` (or point `PY_XBDM_PATH` at it).

## Running it

    python -m xefulive                  # looks for the console on your network
    python -m xefulive 192.168.1.50     # or give it the IP

Or double-click `start-windows.bat`, `start-mac.command` or `start-linux.sh`.

On Linux you may need `sudo apt install python3-tk`. With Homebrew Python on
a Mac you need `brew install python-tk` (or use the python.org installer).

## How to use it

**Memory** is a live hex view. Click a byte and type hex digits to change it
in the running game. The panel on the right shows the selected bytes as a
byte, 2 and 4 bytes, float, double and text, and can write a typed value.
"Show changes since first read" highlights every byte that is different from
the first time it was read.

**Search** is the usual trainer workflow:

1. Type the number you see in the game (say 15) and hit First scan.
   "Number (any type)" checks bytes, 2 bytes, 4 bytes, floats and doubles in one go.
2. Change the number in the game (now it's 27).
3. Type 27 and hit Next scan. What's left are the addresses that went from 15 to 27.

You can also search for changed / didn't change / went up / went down,
unknown values, hex bytes (with ?? wildcards) and text.

**Changes** takes a snapshot of an area and then lists every byte that is
different, with before and after. "Ignore what is changing right now" hides
timers and animation counters so only your own action shows up.

**Mods** is a table of named addresses for the game that is running. Add an
address, pick a type, then set it once or freeze it. Byte patches can be
switched on and off. Tables are saved per game (by title ID) and can be
exported and imported, so you can share them.

Anywhere an address is asked for you can type a formula (numbers are hex):

    BB85B8                  an address
    BB85B8 + 2*6140         third entry of an array of 0x6140 byte records
    [C01234] + 10           follow the pointer stored at C01234, then add 0x10
    player_health           a name you saved under Names

**Tools** has the console connection, an address converter (game address to
the real 360 address, for use in other XBDM tools), saving memory to a file,
and the game's XBE sections.

Pause game freezes the game while you search. Screenshot grabs the console's
screen. Long jobs show a progress bar with a Cancel button, and the rest of
the app keeps working while they run.

## Using it from your own tools

`sdk/` has the same address translation as small layers for C# tools
(XDevkit/XDRPC the way DMONET does it, or plain XBDM) and for C++ code running
on the 360, with a trainer template for each. See [sdk/README.md](sdk/README.md).

## Scripting

    from xefulive import Game

    g = Game("192.168.1.50")
    print(g.title, g.read_float(0xBB85B8))
    g.write_float(0xBB85B8, 999)
    g.write_u8("[C01234] + 10", 3)

## How it works

xefu gives the emulated Xbox its 64 MB of RAM as one block of 360 memory and
runs a real x86 Xbox kernel inside it. So the app finds that block, reads the
game's own x86 page tables out of it, and translates game addresses to 360
addresses that XBDM can read and write.

Things to know:

- Changing data works right away.
- Changing code only works for code the game hasn't run yet. xefu translates
  x86 code to PowerPC and keeps the translation, so patching an instruction
  that already ran does nothing.
- The app uses one connection to the console. While a game is running XBDM
  only gets a little CPU time (about 100 KB/s), but with the game stopped it
  does about 1 MB/s. So big reads (scans, snapshots, dumps) pause the game
  while they run, usually for a few seconds, then resume it. You can turn
  that off in Tools, it is just a lot slower.
- If the game ever stays frozen (say the app was killed in the middle of a
  read), press Pause game and then Resume game.

## Credits

[py-xbdm](https://github.com/XeCrippy/py-xbdm) by XeCrippy does the talking
to the console.
