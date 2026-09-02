# Lessons In Love Walkthrough Guide Tool

Would you like help with understanding what the next step in your Lessons in Love playthrough should be? This is the tool for you!

Lessons In Love Guide Tool looks at your most recent save game, and lets you know what events you can perform next and their requirements. End all the endless trial and error to find the next event to trigger!

Also see [the guide tool website here](http://largestack.github.io/Lessons-In-Love-Guide-Tool/) for a list of events and code corresponding to game events. You can go here if you are stuck on an event to see the code.

## Game version supported
The guide reads event definitions directly from the installed game. This build
supports current Ren'Py save formats used by Lessons in Love 0.61 and remains
compatible with older primitive save values.

## Installation - Windows
Download the [latest release](https://github.com/largestack/Lessons-In-Love-Guide-Tool/releases) executable here and run it.

## Installation - Linux or macOS
1. Download and extract the entire repo.
2. Install Python 3.9 or newer. Tkinter is included with many Python installs;
   Linux distributions may provide it as a package such as `python3-tk`.
3. From a terminal, run `python main.py` or `python3 main.py`.

`webbrowser` and all other runtime modules are part of Python's standard
library; no `pip` runtime packages are required.

## Using the tool

1. Run the tool.
1. On first run, it will ask you to select the base game folder.
1. It will automatically load the most recent save-game every time it loads.
1. You can also hit the "Reload" to load the most recent save game again. You can do this to refresh the guide tool while you play the game. Simply save your game, then hit "Reload" to update the guide.

<img src="./docs/images/UserInterface.png" width="70%" height="70%">

* **Suggested next events**: Click on these events to see what's required for
  the next suggested events. An active automatic chain shows its origin and
  current step.
* **Event group**: Browse events by character; Main events are split by chapter.
* **Event**: Search event names/ids, filter by status, or browse the selected group.
* **Event prerequisites**: The requirements for the event to trigger. "Unmet
  only" explains what is blocking it and shows the latest save value.
* **Event raw details**: Event metadata, evaluated conditions, and the original
  Ren'Py event/trigger source used by the guide.

Quick navigation buttons jump to the latest completed Main event, the next
incomplete Main event, the current chain step, or the missable-event dashboard.
The missable dashboard separates events that are at risk, already missed, and
still open. Window size, filters, the unmet-only choice, selection, and scroll
positions are remembered between launches; an updated save still defaults to
the latest completed Main event.

The guide automatically notices a new or updated save and reloads it after the
file has settled. Events can be bookmarked with the star button and reviewed
from the Bookmarks list. "Show path" displays the shortest unfinished event
dependency chain to the selected event. Missed and endangered scenes include
the evaluated miss rule and current save values.

Spoilers mode replaces future and missed event names with `???` and hides their
raw source details. Parser health reports replay coverage, script-file count,
cache use, unsupported expressions, missing save variables, and load warnings.

Keyboard shortcuts: `Ctrl+F` searches, `F5` reloads, `Alt+Left` goes back,
`Ctrl+M` opens the latest Main event, `Ctrl+N` opens the next Main event,
`Ctrl+H` opens the current chain, `Ctrl+B` toggles a bookmark,
`Ctrl+Shift+B` opens Bookmarks, and `Escape` clears special views and filters.

Status icons are: ✅ completed, 🔵 ready now, ⏭ missed/skipped, and ❌ not yet
available. Reload keeps the current data visible if a new save is still being
written, automatically falls back to the next-newest readable save, and reuses
the parsed event structure while the installed Ren'Py scripts are unchanged.

Event colors follow the game's replay menu: red (`#EF1A1A`) marks missable
events, blue (`#778EFF`) marks invite-over events, and pink (`#FF85FD`) marks
lust events. A red `(!)` identifies missable entries in the normal event list.
When an automatic chain is in progress, Suggested next events shows its current
step and continuation; missed titles are revealed only after they are missed or
become unavoidable inside that active chain.

Each event group displays its completed/total counter, and the Event groups
header shows the completed/total count across the whole game.
