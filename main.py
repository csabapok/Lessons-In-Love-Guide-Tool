# Import Module
from tkinter import messagebox
import webbrowser
from tkinter import *
import json
import os
import re
import sys
import time
from tkinter import filedialog
import game_data
from tooltip import Tooltip

# Create the Tkinter UI
import tkinter as tk
import tkinter.font as tkFont


import tkinter as tk
import tkinter.ttk as ttk


def comparison_symbol_to_text(comparison_symbol):
  if comparison_symbol == ">":
    return "greater than"
  elif comparison_symbol == ">=":
    return "greater than or equal to"
  elif comparison_symbol == "<":
    return "less than"
  elif comparison_symbol == "<=":
    return "less than or equal to"
  elif comparison_symbol == "==":
    return "equal to"
  elif comparison_symbol == "!=":
    return "not equal to"
  elif comparison_symbol == "in":
    return "contained in"
  elif comparison_symbol == "not in":
    return "not contained in"
  elif comparison_symbol == "is":
    return "is"
  elif comparison_symbol == "is not":
    return "is not"
  else:
    return comparison_symbol


def event_status_icon(event):
  if event.get("complete"):
    return "✅"
  if event.get("missed"):
    return "⏭"
  if event.get("ready_to_trigger"):
    return "🔵"
  return "❌"


MISSABLE_EVENT_COLOR = "#EF1A1A"
INVITE_EVENT_COLOR = "#778EFF"
LUST_EVENT_COLOR = "#FF85FD"
DEFAULT_EVENT_COLOR = "#333333"


def _ui_state_path():
  if getattr(sys, "frozen", False):
    base_folder = os.path.dirname(sys.executable)
  else:
    base_folder = os.path.dirname(os.path.abspath(__file__))
  return os.path.join(base_folder, "guide_ui_state.json")


def load_ui_state():
  try:
    with open(_ui_state_path(), "r", encoding="utf8") as state_file:
      state = json.load(state_file)
    return state if isinstance(state, dict) else {}
  except (OSError, ValueError, TypeError):
    return {}


def save_ui_state(state):
  try:
    with open(_ui_state_path(), "w", encoding="utf8") as state_file:
      json.dump(state, state_file, indent=2)
    return True
  except OSError:
    return False


def event_is_missable(event):
  return bool(event.get("miss_condition_text"))


def event_name_for_display(event, show_missed_name=False):
  if show_missed_name and event.get("missed_name"):
    return event["missed_name"]
  return event["name"]


def event_display_color(event):
  if event_is_missable(event):
    return MISSABLE_EVENT_COLOR
  if event.get("category") == "invite":
    return INVITE_EVENT_COLOR
  if event.get("category") == "lust":
    return LUST_EVENT_COLOR
  return DEFAULT_EVENT_COLOR


def event_completion_count(events):
  """Returns completed/total for the actual replay entries in the game."""
  event_list = list(events)
  completed = sum(bool(event.get("complete")) for event in event_list)
  return completed, len(event_list)


def event_browser_group(event):
  """Returns the UI section for an event without changing its game group."""
  if event.get("group") == "Main" and event.get("chapter"):
    return f'Main — {event["chapter"]}'
  return event.get("group", "")


def order_event_group_names(group_names):
  """Places every Main chapter first while preserving character order."""
  main_groups = []
  other_groups = []
  for group_name in group_names:
    match = re.fullmatch(r"Main — Chapter (\d+)", group_name)
    if match:
      main_groups.append((int(match.group(1)), group_name))
    else:
      other_groups.append(group_name)
  return [name for _, name in sorted(main_groups)] + other_groups


def is_structural_chapter_condition(variable):
  """Chapter activation gates are structural, not useful event prerequisites."""
  return bool(re.fullmatch(r"(?:chap\d+|chapter)_?active", variable or ""))


def latest_completed_main_event(events):
  """Returns the last completed Main replay entry in game menu order."""
  main_events = [event for event in events if event.get("group") == "Main"]
  return next(
    (event for event in reversed(main_events) if event.get("complete")),
    None,
  )


def next_incomplete_main_event(events):
  """Returns the first unresolved Main event after the latest progress."""
  main_events = [event for event in events if event.get("group") == "Main"]
  last_progress = max(
    (
      index
      for index, event in enumerate(main_events)
      if event.get("complete") or event.get("missed")
    ),
    default=-1,
  )
  return next(
    (
      event
      for event in main_events[last_progress + 1:]
      if not event.get("complete") and not event.get("missed")
    ),
    next(
      (
        event
        for event in main_events
        if not event.get("complete") and not event.get("missed")
      ),
      None,
    ),
  )


def calculate_active_chain(events):
  """Returns the missed/current/future entries of an automatic chain in progress."""
  event_list = list(events)
  events_by_id = {event["id"]: event for event in event_list}
  successors = {}
  for event in event_list:
    source_id = event.get("chain_sources")
    if source_id in events_by_id:
      successors.setdefault(source_id, []).append(event)

  frontiers = []
  for event in event_list:
    if event.get("complete") or event.get("missed"):
      continue
    source = events_by_id.get(event.get("chain_sources"))
    if source and (source.get("complete") or source.get("missed")):
      frontiers.append(event)

  chain_events = []
  seen = set()

  def add(event):
    if event["id"] not in seen:
      seen.add(event["id"])
      chain_events.append(event)

  for frontier in frontiers:
    missed_ancestors = []
    source = events_by_id.get(frontier.get("chain_sources"))
    while source and source.get("missed") and source["id"] not in seen:
      missed_ancestors.append(source)
      source = events_by_id.get(source.get("chain_sources"))
    for ancestor in reversed(missed_ancestors):
      add(ancestor)

    queue = [frontier]
    expanded = set()
    while queue:
      current = queue.pop(0)
      if current["id"] in expanded:
        continue
      expanded.add(current["id"])
      if not current.get("complete"):
        add(current)
      queue.extend(successors.get(current["id"], []))

  return chain_events


def active_chain_origin(events, chain_events):
  """Returns the earliest replay event that leads into an active chain."""
  if not chain_events:
    return None
  events_by_id = {event["id"]: event for event in events}
  origin = chain_events[0]
  seen = set()
  while origin.get("chain_sources") in events_by_id:
    if origin["id"] in seen:
      break
    seen.add(origin["id"])
    origin = events_by_id[origin["chain_sources"]]
  return origin


def missable_event_sections(events, active_chain_ids):
  """Splits unfinished missables into endangered, missed, and recoverable."""
  endangered = []
  missed = []
  recoverable = []
  for event in events:
    if not event_is_missable(event) or event.get("complete"):
      continue
    if event.get("missed"):
      missed.append(event)
    elif (
      event["id"] in active_chain_ids
      and event.get("requirements_satisfied") is False
    ):
      endangered.append(event)
    else:
      recoverable.append(event)
  return endangered, missed, recoverable


def shortest_prerequisite_path(events, target_event):
  """Returns the shortest unresolved event-dependency path to a target."""
  events_by_id = {
    event["id"]: event
    for event in events
  }

  def unresolved_dependencies(event):
    dependency_ids = list(event.get("required_events", []))
    if event.get("chain_sources"):
      dependency_ids.append(event["chain_sources"])
    dependencies = []
    for dependency_id in dict.fromkeys(dependency_ids):
      dependency = events_by_id.get(dependency_id)
      if dependency is None or dependency.get("complete"):
        continue
      dependencies.append(dependency)
    return dependencies

  def walk(event, visiting):
    if event["id"] in visiting:
      return [event]
    dependencies = unresolved_dependencies(event)
    if not dependencies:
      return [event]
    paths = [
      walk(dependency, visiting | {event["id"]}) + [event]
      for dependency in dependencies
    ]
    return min(paths, key=lambda path: (len(path), path[0]["id"]))

  return walk(target_event, set())


def save_folder_signature(save_folder):
  """Cheaply fingerprints the newest save and persistent replay state."""
  entries = []
  try:
    names = os.listdir(save_folder)
  except OSError:
    return ()
  for name in names:
    if not name.endswith(".save") and name != "persistent":
      continue
    path = os.path.join(save_folder, name)
    try:
      stat = os.stat(path)
    except OSError:
      continue
    entries.append((name, stat.st_mtime_ns, stat.st_size))
  return tuple(sorted(entries))


def chain_event_uses_missed_name(event, active_chain_ids):
  """Shows an actual or now-unavoidable missed title inside an active chain."""
  return bool(
    event_is_missable(event)
    and (
      event.get("missed")
      or (
        event["id"] in active_chain_ids
        and event.get("requirements_satisfied") is False
      )
    )
  )


def calculate_event_suggestions(group_to_events, characters):
  """Returns useful next events, including branch-triggered character scenes."""
  suggestions = []
  seen = set()
  group_order = ["Main"] + [name.capitalize() for name in characters]

  for group in group_order:
    group_events = group_to_events.get(group, [])
    if not group_events:
      continue

    unresolved = [
      event
      for event in group_events
      if not event.get("complete")
      and not event.get("missed")
      and not event.get("chain_sources")
    ]
    if not unresolved:
      continue

    if group == "Main":
      last_progress = max(
        (
          index
          for index, event in enumerate(group_events)
          if event.get("complete") or event.get("missed")
        ),
        default=-1,
      )
      after_progress = [
        event
        for event in group_events[last_progress + 1:]
        if event in unresolved
      ]
      selected = (after_progress or unresolved)[:1]
    else:
      progress_indexes = [
        index
        for index, event in enumerate(group_events)
        if event.get("complete") or event.get("missed")
      ]
      start_index = progress_indexes[-2] + 1 if len(progress_indexes) >= 2 else 0
      recent_unresolved = [
        event
        for event in group_events[start_index:]
        if event in unresolved
      ]
      ready = [
        event
        for event in recent_unresolved
        if event.get("ready_to_trigger")
      ]
      selected = ready[:3]

    for event in selected:
      if event["id"] not in seen:
        seen.add(event["id"])
        suggestions.append(event)

  return suggestions

class App:
  def __init__(self, root):
    #setting title
    root.title("Lessons in Love: Walkthrough guide v1.5d")
    self.root = root
    self.ui_state = load_ui_state()
    self.active_event = None
    self.visible_events = []
    self.active_chain_events = []
    self.active_chain_event_ids = set()
    self.active_chain_missed_ids = set()
    self.active_chain_current_id = None
    self.current_save_signature = None
    self.missable_dashboard_active = False
    self.bookmark_dashboard_active = False
    self.bookmark_ids = {
      str(event_id)
      for event_id in self.ui_state.get("bookmarks", [])
    }
    self._refreshing = False
    self._save_watch_job = None
    self._last_seen_save_fs_signature = None
    self._pending_save_fs_signature = None
    self._last_auto_reload_time = None
    self._changing_filters = False
    self._base_layout = {}

    #setting window size
    try:
      width = int(self.ui_state.get("width", 1236))
      height = int(self.ui_state.get("height", 633))
    except (TypeError, ValueError):
      width, height = 1236, 633
    screenwidth = root.winfo_screenwidth()
    screenheight = root.winfo_screenheight()
    width = max(990, min(width, screenwidth))
    height = max(520, min(height, screenheight))
    alignstr = '%dx%d+%d+%d' % (width, height, (screenwidth - width) / 2, (screenheight - height) / 2)
    root.geometry(alignstr)
    root.minsize(width=990, height=520)
    root.resizable(width=True, height=True)

    GLabel_220=tk.Label(root)
    ft = tkFont.Font(family='Times',size=10)
    GLabel_220["font"] = ft
    GLabel_220["fg"] = "#333333"
    GLabel_220["justify"] = "left"
    GLabel_220["text"] = "Suggested next events"
    GLabel_220.place(x=10,y=5,width=217,height=35)
    self.label_suggestions = GLabel_220

    list_event_suggestions=tk.Listbox(root, exportselection=False)
    list_event_suggestions["borderwidth"] = "1px"
    ft = tkFont.Font(family='Times',size=10)
    list_event_suggestions["font"] = ft
    list_event_suggestions["fg"] = "#333333"
    list_event_suggestions.place(x=10,y=40,width=217,height=217)
    list_event_suggestions.bind("<<ListboxSelect>>", self.on_list_event_suggestions_select)
    self.list_event_suggestions = list_event_suggestions

    button_latest_main=ttk.Button(root, text="Latest Main", command=self.button_latest_main)
    button_latest_main.place(x=10,y=261,width=105,height=21)
    Tooltip(button_latest_main, text="Jump to the latest completed Main event.")

    button_next_main=ttk.Button(root, text="Next Main", command=self.button_next_main)
    button_next_main.place(x=121,y=261,width=106,height=21)
    Tooltip(button_next_main, text="Jump to the next incomplete Main event.")

    button_current_chain=ttk.Button(root, text="Current chain", command=self.button_current_chain)
    button_current_chain.place(x=10,y=284,width=105,height=21)
    Tooltip(button_current_chain, text="Jump to your current automatic chain event.")

    button_missables=ttk.Button(root, text="Missables", command=self.button_missables)
    button_missables.place(x=121,y=284,width=106,height=21)
    Tooltip(button_missables, text="Show endangered, missed, and still-recoverable missable events.")

    button_bookmarks=ttk.Button(root, text="Bookmarks", command=self.button_bookmarks)
    button_bookmarks.place(x=10,y=307,width=217,height=21)
    Tooltip(button_bookmarks, text="Show events you bookmarked for this playthrough.")

    GLabel_221=tk.Label(root)
    ft = tkFont.Font(family='Times',size=10)
    GLabel_221["font"] = ft
    GLabel_221["fg"] = "#333333"
    GLabel_221["justify"] = "left"
    GLabel_221["text"] = "Save game details\n(auto loads most recent)"
    GLabel_221.place(x=-30,y=330,width=236,height=40)

    text_save_details=tk.Text(root)
    text_save_details["borderwidth"] = "1px"
    ft = tkFont.Font(family="Consolas 10",size=10)
    text_save_details["font"] = ft
    text_save_details["fg"] = "#333333"
    text_save_details.insert(tk.END,"Save details go here")
    text_save_details.place(x=10,y=370,width=217,height=237)
    self.text_save_details = text_save_details

    
    list_event_groups=tk.Listbox(root, exportselection=False)
    list_event_groups["borderwidth"] = "1px"
    ft = tkFont.Font(family='Times',size=10)
    list_event_groups["font"] = ft
    list_event_groups["fg"] = "#333333"
    list_event_groups.place(x=230,y=40,width=247,height=588)
    self.list_event_groups = list_event_groups
    list_event_groups.bind("<<ListboxSelect>>", self.on_list_event_groups_select)

    GLabel_558=tk.Label(root)
    ft = tkFont.Font(family='Times',size=10)
    GLabel_558["font"] = ft
    GLabel_558["fg"] = "#333333"
    GLabel_558["justify"] = "left"
    GLabel_558["text"] = "Event groups"
    GLabel_558.place(x=240,y=10,width=230,height=25)
    self.label_event_groups = GLabel_558

    list_events=tk.Listbox(root, exportselection=False)
    list_events["borderwidth"] = "1px"
    ft = tkFont.Font(family='Times',size=10)
    list_events["font"] = ft
    list_events["fg"] = "#333333"
    list_events.place(x=480,y=40,width=262,height=588)
    self.list_events = list_events
    list_events.bind("<<ListboxSelect>>", self.on_list_events_select)
    # Add a scrollbar to the listbox
    scrollbar = tk.Scrollbar(root, orient="vertical")
    scrollbar.config(command=list_events.yview)
    scrollbar.pack(side="right", fill="y")
    list_events.config(yscrollcommand=scrollbar.set)
    # Position the scrollbar next to it
    scrollbar.place(x=480+246, y=40, width=20, height=588)


    GLabel_939=tk.Label(root)
    ft = tkFont.Font(family='Times',size=10)
    GLabel_939["font"] = ft
    GLabel_939["fg"] = "#333333"
    GLabel_939["justify"] = "left"
    GLabel_939["text"] = "Event"
    GLabel_939.place(x=480,y=10,width=80,height=25)
    self.label_events = GLabel_939

    self.search_var = tk.StringVar(value=str(self.ui_state.get("search", "")))
    search_entry = ttk.Entry(root, textvariable=self.search_var)
    search_entry.place(x=560, y=9, width=80, height=25)
    self.search_var.trace_add("write", self.on_search_changed)
    self.search_entry = search_entry
    Tooltip(search_entry, text="Search event names, ids, and groups.")

    saved_status = self.ui_state.get("status_filter", "All")
    valid_statuses = ("All", "Incomplete", "Ready now", "Completed", "Missed")
    if saved_status not in valid_statuses:
      saved_status = "All"
    self.status_filter_var = tk.StringVar(value=saved_status)
    status_filter = ttk.Combobox(
      root,
      textvariable=self.status_filter_var,
      values=valid_statuses,
      state="readonly",
    )
    status_filter.place(x=644, y=9, width=95, height=25)
    status_filter.bind("<<ComboboxSelected>>", self.on_search_changed)
    Tooltip(status_filter, text="Filter the event list by its current status.")

    GLabel_658=tk.Label(root)
    ft = tkFont.Font(family='Times',size=10)
    GLabel_658["font"] = ft
    GLabel_658["fg"] = "#333333"
    GLabel_658["justify"] = "center"
    GLabel_658["text"] = "Prerequisites (click event rows to jump)"
    GLabel_658.place(x=740,y=10,width=245,height=30)
    self.label_prerequisites = GLabel_658

    self.spoiler_mode_var = tk.BooleanVar(
      value=bool(self.ui_state.get("spoiler_mode", False))
    )
    spoiler_mode=ttk.Checkbutton(
      root,
      text="Hide spoilers",
      variable=self.spoiler_mode_var,
      command=self.on_spoiler_mode_changed,
    )
    spoiler_mode.place(x=990,y=10,width=88,height=25)
    Tooltip(spoiler_mode, text="Hide future and missed event names and raw details.")

    list_event_prereq_events=tk.Listbox(root, exportselection=False)
    list_event_prereq_events["borderwidth"] = "1px"
    ft = tkFont.Font(family='Times',size=10)
    list_event_prereq_events["font"] = ft
    list_event_prereq_events["fg"] = "#333333"
    list_event_prereq_events.place(x=750,y=40,width=481,height=230)
    list_event_prereq_events.bind("<<ListboxSelect>>", self.on_list_event_prereq_events_select)
    self.list_event_prereq_events = list_event_prereq_events

    GLabel_650=tk.Label(root)
    ft = tkFont.Font(family='Times',size=10)
    GLabel_650["font"] = ft
    GLabel_650["fg"] = "#333333"
    GLabel_650["justify"] = "center"
    GLabel_650["text"] = "Event raw details"
    GLabel_650.place(x=740,y=270,width=128,height=30)

    legend_missable=tk.Label(root, text="(!) Missable", fg=MISSABLE_EVENT_COLOR, justify="left")
    legend_missable.place(x=868,y=273,width=76,height=25)
    legend_invite=tk.Label(root, text="Invite", fg=INVITE_EVENT_COLOR, justify="left")
    legend_invite.place(x=945,y=273,width=45,height=25)
    legend_lust=tk.Label(root, text="Lust", fg=LUST_EVENT_COLOR, justify="left")
    legend_lust.place(x=990,y=273,width=40,height=25)

    self.unmet_only_var = tk.BooleanVar(
      value=bool(self.ui_state.get("unmet_only", True))
    )
    unmet_only=ttk.Checkbutton(
      root,
      text="Unmet only",
      variable=self.unmet_only_var,
      command=self.on_unmet_only_changed,
    )
    unmet_only.place(x=1035,y=273,width=95,height=25)
    Tooltip(unmet_only, text="Show only requirements that the latest save has not met.")

    button_path=ttk.Button(root, text="Show path", command=self.button_show_path)
    button_path.place(x=1135,y=273,width=95,height=25)
    Tooltip(button_path, text="Show the shortest unresolved event path to the selected event.")

    text_event_details=tk.Text(root)
    text_event_details["borderwidth"] = "1px"
    ft = tkFont.Font(family="Consolas 10",size=10)
    text_event_details["font"] = ft
    text_event_details["fg"] = "#333333"
    text_event_details["wrap"] = "word"
    text_event_details.insert(tk.END,"Event details go here")
    text_event_details.place(x=750,y=300,width=460,height=279)
    self.text_code_snippets = text_event_details
    # Add scroll bar
    scrollbar = tk.Scrollbar(root, orient="vertical", command=text_event_details.yview)
    text_event_details.config(yscrollcommand=scrollbar.set)
    scrollbar.place(x=1210, y=300, width=18, height=279)

    button_event_wiki=tk.Button(root)
    button_event_wiki["bg"] = "#f0f0f0"
    ft = tkFont.Font(family='Times',size=10)
    button_event_wiki["font"] = ft
    button_event_wiki["fg"] = "#000000"
    button_event_wiki["justify"] = "center"
    button_event_wiki["text"] = "Open wiki for this event"
    button_event_wiki.place(x=890,y=590,width=137,height=30)
    button_event_wiki["command"] = self.button_event_wiki
    button_event_wiki_ttp = Tooltip(button_event_wiki, text="Opens this event on the official wiki.")

    button_bookmark=tk.Button(root)
    button_bookmark["bg"] = "#f0f0f0"
    button_bookmark["font"] = ft
    button_bookmark["fg"] = "#000000"
    button_bookmark["justify"] = "center"
    button_bookmark["text"] = "☆ Bookmark"
    button_bookmark.place(x=750,y=590,width=125,height=30)
    button_bookmark["command"] = self.button_toggle_bookmark
    self.button_bookmark = button_bookmark
    Tooltip(button_bookmark, text="Bookmark or unbookmark the selected event (Ctrl+B).")

    button_parser_health=tk.Button(root)
    button_parser_health["bg"] = "#f0f0f0"
    button_parser_health["font"] = ft
    button_parser_health["fg"] = "#000000"
    button_parser_health["justify"] = "center"
    button_parser_health["text"] = "Parser health"
    button_parser_health.place(x=1040,y=590,width=188,height=30)
    button_parser_health["command"] = self.button_parser_health
    Tooltip(button_parser_health, text="Show parser coverage, warnings, and unsupported conditions.")

    button_refresh=tk.Button(root)
    button_refresh["bg"] = "#f0f0f0"
    ft = tkFont.Font(family='Times',size=10)
    button_refresh["font"] = ft
    button_refresh["fg"] = "#000000"
    button_refresh["justify"] = "center"
    button_refresh["text"] = "Reload"
    button_refresh.place(x=50,y=590,width=136,height=30)
    button_refresh["command"] = self.button_refresh
    button_refresh_ttp = Tooltip(button_refresh, text="Reloads everything from the most recent save file again.")

    button_back=tk.Button(root)
    button_back["bg"] = "#f0f0f0"
    ft = tkFont.Font(family='Times',size=10)
    button_back["font"] = ft
    button_back["fg"] = "#000000"
    button_back["justify"] = "center"
    button_back["text"] = "Back to previous event"
    button_back.place(x=1080,y=5,width=152,height=30)
    button_back["command"] = self.button_back
    button_back_ttp = Tooltip(button_back, text="Go back to the previous event that you were most recently viewing.")

    self._capture_base_layout(root)
    root.bind("<Configure>", self.on_window_resize)
    root.bind("<Control-f>", self.focus_search)
    root.bind("<F5>", self.keyboard_reload)
    root.bind("<Alt-Left>", self.keyboard_back)
    root.bind("<Control-m>", self.keyboard_latest_main)
    root.bind("<Control-n>", self.keyboard_next_main)
    root.bind("<Control-h>", self.keyboard_current_chain)
    root.bind("<Control-b>", self.keyboard_toggle_bookmark)
    root.bind("<Control-Shift-B>", self.keyboard_bookmarks)
    root.bind("<Escape>", self.keyboard_clear_filters)
    root.protocol("WM_DELETE_WINDOW", self.on_close)

    # Load the game folder if it exists
    game_folder = None
    if os.path.exists("game_folder.txt"):
      with open("game_folder.txt", "r") as f:
        game_folder = f.read().strip()

    # Prompt the user to select the game folder
    if game_folder is None:
      game_folder = filedialog.askdirectory(title="Select the game folder")
    while not game_folder or not os.path.exists(os.path.join(game_folder, "game", "script.rpy")):
      print("Invalid game folder. Please select the root folder of the game.")
      game_folder = filedialog.askdirectory(title="Select the game folder")
      if not game_folder:
        root.destroy()
        return
    self.game_folder = game_folder

    # Write the game folder to a file
    with open("game_folder.txt", "w") as f:
      f.write(game_folder)

    self.refresh()
    self._last_seen_save_fs_signature = self._current_save_fs_signature()
    self._schedule_save_watch()

  def _capture_base_layout(self, root):
    for widget in root.winfo_children():
      place = widget.place_info()
      if not place:
        continue
      try:
        self._base_layout[widget] = {
          key: int(float(place[key]))
          for key in ("x", "y", "width", "height")
        }
      except (KeyError, ValueError):
        continue

  def on_window_resize(self, event):
    if event.widget is not self.root or not self._base_layout:
      return
    scale_x = event.width / 1236
    scale_y = event.height / 633
    for widget, geometry in self._base_layout.items():
      if not widget.winfo_exists():
        continue
      widget.place(
        x=round(geometry["x"] * scale_x),
        y=round(geometry["y"] * scale_y),
        width=max(20, round(geometry["width"] * scale_x)),
        height=max(20, round(geometry["height"] * scale_y)),
      )

  def on_close(self):
    if self._save_watch_job is not None:
      try:
        self.root.after_cancel(self._save_watch_job)
      except tk.TclError:
        pass
    selected_event_id = self.active_event["id"] if self.active_event else None
    state = {
      "width": self.root.winfo_width(),
      "height": self.root.winfo_height(),
      "selected_event_id": selected_event_id,
      "save_signature": self.current_save_signature,
      "search": self.search_var.get(),
      "status_filter": self.status_filter_var.get(),
      "unmet_only": self.unmet_only_var.get(),
      "spoiler_mode": self.spoiler_mode_var.get(),
      "bookmarks": sorted(self.bookmark_ids),
      "group_scroll": self.list_event_groups.yview()[0],
      "event_scroll": self.list_events.yview()[0],
      "suggestion_scroll": self.list_event_suggestions.yview()[0],
    }
    save_ui_state(state)
    self.root.destroy()

  def _current_save_fs_signature(self):
    return save_folder_signature(
      os.path.join(self.game_folder, "game", "saves")
    )

  def _schedule_save_watch(self):
    try:
      if self.root.winfo_exists():
        self._save_watch_job = self.root.after(1500, self._watch_save_folder)
    except tk.TclError:
      self._save_watch_job = None

  def _watch_save_folder(self):
    self._save_watch_job = None
    try:
      signature = self._current_save_fs_signature()
      if signature != self._last_seen_save_fs_signature:
        if signature == self._pending_save_fs_signature and not self._refreshing:
          self._pending_save_fs_signature = None
          self._last_auto_reload_time = time.strftime("%H:%M:%S")
          if self.refresh() and not any(
            warning.startswith("Skipped unreadable save")
            for warning in game_data.last_load_warnings
          ):
            self._last_seen_save_fs_signature = signature
        else:
          self._pending_save_fs_signature = signature
      else:
        self._pending_save_fs_signature = None
    except (OSError, tk.TclError):
      pass
    self._schedule_save_watch()

  def _restore_ui_scroll_positions(self):
    for key, listbox in (
      ("group_scroll", self.list_event_groups),
      ("event_scroll", self.list_events),
      ("suggestion_scroll", self.list_event_suggestions),
    ):
      try:
        listbox.yview_moveto(float(self.ui_state.get(key, 0)))
      except (TypeError, ValueError, tk.TclError):
        pass

  def _spoiler_hidden(self, event, show_missed_name=False):
    if not self.spoiler_mode_var.get():
      return False
    if event.get("missed") or show_missed_name:
      return True
    return bool(
      not event.get("complete")
      and not event.get("ready_to_trigger")
      and event["id"] != self.active_chain_current_id
    )

  def _event_name(self, event, show_missed_name=False):
    if self._spoiler_hidden(event, show_missed_name):
      return "???"
    return event_name_for_display(event, show_missed_name)

  def _condition_row(self, condition, event):
    """Turns a parsed requirement into a compact, save-aware UI row."""
    icon = "✅" if condition["satisfied"] else "❌"
    variable = condition["variable"]
    comparison = condition["comparison"]
    value = condition["value"]
    target_event = None

    if variable in {event["id"], event["completion_variable"]}:
      return None, None

    if variable == "day":
      days = {
        1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
        5: "Friday", 6: "Saturday", 7: "Sunday",
      }
      try:
        day = days[int(value)]
      except (KeyError, TypeError, ValueError):
        day = str(value)
      if comparison == "==":
        text = f"Day of week is {day}"
      elif comparison == "!=":
        text = f"Day of week is not {day}"
      elif comparison in (">", ">=") and value in (5, 6):
        text = "Day of week is a weekend"
      elif comparison in ("<", "<=") and value in (5, 6):
        text = "Day of week is a weekday"
      else:
        text = f"Day of week {comparison_symbol_to_text(comparison)} {day}"
    elif variable.endswith("_love"):
      character = variable.removesuffix("_love").capitalize()
      text = f"{character} love {comparison_symbol_to_text(comparison)} {value}"
    elif variable.endswith("_lust"):
      character = variable.removesuffix("_lust").capitalize()
      text = f"{character} lust {comparison_symbol_to_text(comparison)} {value}"
    elif condition.get("event_id") in self.events:
      condition_event_id = condition["event_id"]
      target_event = self.events[condition_event_id]
      name = self._event_name(
        target_event,
        bool(target_event.get("missed")),
      )
      if comparison == "==" and value is True:
        text = f'Event "{name}" is completed (event={condition_event_id})'
      elif comparison == "==" and value is False:
        text = f'Event "{name}" must not be completed (event={condition_event_id})'
      elif comparison == "!=" and value is True:
        text = f'Event "{name}" must not be completed (event={condition_event_id})'
      elif comparison == "!=" and value is False:
        text = f'Event "{name}" is completed (event={condition_event_id})'
      else:
        text = (
          f'Event "{name}" {comparison_symbol_to_text(comparison)} {value} '
          f'(event={condition_event_id})'
        )
    elif variable == "totaldays":
      text = (
        "Days since the start of the game "
        f"{comparison_symbol_to_text(comparison)} {value}"
      )
    else:
      text = (
        f"{variable} {comparison_symbol_to_text(comparison)} {value}"
      )

    if not condition["satisfied"]:
      current_value = condition.get("saved_value")
      if variable == "day":
        try:
          current_value = {
            1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
            5: "Friday", 6: "Saturday", 7: "Sunday",
          }.get(int(current_value), current_value)
        except (TypeError, ValueError):
          pass
      text += f" — current: {current_value!r}"
    return icon + text, target_event

  def _matches_status_filter(self, event):
    status = self.status_filter_var.get()
    if status == "All":
      return True
    if status == "Incomplete":
      return not event.get("complete") and not event.get("missed")
    if status == "Ready now":
      return bool(event.get("ready_to_trigger"))
    if status == "Completed":
      return bool(event.get("complete"))
    if status == "Missed":
      return bool(event.get("missed"))
    return True

  def _insert_colored_row(self, listbox, text, event=None):
    row_index = listbox.size()
    listbox.insert(tk.END, text)
    if event is not None:
      listbox.itemconfig(row_index, fg=event_display_color(event))
    return row_index

  def _insert_prerequisite(self, text, event=None):
    return self._insert_colored_row(
      self.list_event_prereq_events,
      text,
      event,
    )

  def _populate_event_list(self, events, include_group=False):
    self.visible_events = list(events)
    self.list_events.delete(0, tk.END)
    for event in self.visible_events:
      label = self._event_name(event, bool(event.get("missed")))
      if event_is_missable(event):
        label = "(!) " + label
      if event["id"] in self.bookmark_ids:
        label = "★ " + label
      if include_group:
        label = event_browser_group(event) + ": " + label
      self._insert_colored_row(
        self.list_events,
        event_status_icon(event) + " " + label,
        event,
      )

  def on_search_changed(self, *_):
    if self._changing_filters or not hasattr(self, "events"):
      return
    self.missable_dashboard_active = False
    self.bookmark_dashboard_active = False
    self.label_events["text"] = "Event"
    query = self.search_var.get().strip().casefold()
    global_filter = bool(query) or self.status_filter_var.get() != "All"
    if global_filter:
      source = self.events.values()
    elif self.active_event is not None:
      source = self.group_to_events.get(event_browser_group(self.active_event), [])
    else:
      source = []

    filtered = []
    for event in source:
      searchable = " ".join(
        (event["name"], event["id"], event["group"], event_browser_group(event))
      ).casefold()
      if query and query not in searchable:
        continue
      if not self._matches_status_filter(event):
        continue
      filtered.append(event)
    self._populate_event_list(filtered, include_group=global_filter)

  def previous_event(self):
    if len(self.previous_events) > 1:
      self.previous_events.pop()
      self.select_event(self.previous_events.pop())

  def select_event(self, event, add_to_history=True):

    if event is None:
      self.active_event = event
      self.visible_events = []

      # Unselect list boxes
      self.list_event_suggestions.selection_clear(0, tk.END)
      self.list_event_groups.selection_clear(0, tk.END)
      self.list_events.selection_clear(0, tk.END)
      self.list_event_prereq_events.selection_clear(0, tk.END)
      self.list_event_prereq_events.delete(0, tk.END)
      self.text_code_snippets.delete(1.0, tk.END)
      self.text_code_snippets.insert(tk.END, "No event selected.")
      self.button_bookmark["text"] = "☆ Bookmark"

      # Update the event list box
      self.list_events.delete(0, tk.END)
      return

    global_filter = (
      bool(self.search_var.get().strip())
      or self.status_filter_var.get() != "All"
      or self.missable_dashboard_active
      or self.bookmark_dashboard_active
    )
    if (
      not global_filter
      and (
        self.active_event is None
        or event_browser_group(event) != event_browser_group(self.active_event)
      )
    ):
      self._populate_event_list(self.group_to_events[event_browser_group(event)])
      
    self.active_event = event
    self.button_bookmark["text"] = (
      "★ Bookmarked" if event["id"] in self.bookmark_ids else "☆ Bookmark"
    )

    # Unselect list boxes
    self.list_event_suggestions.selection_clear(0, tk.END)
    self.list_event_groups.selection_clear(0, tk.END)
    self.list_events.selection_clear(0, tk.END)
    self.list_event_prereq_events.selection_clear(0, tk.END)
    
    if add_to_history and (not self.previous_events or self.previous_events[-1] is not event):
      self.previous_events.append(self.active_event)
    
    # Select the event in the list boxes
    if event in self.event_suggestions:
      suggestion_index = self.event_suggestions.index(event)
      self.list_event_suggestions.selection_set(suggestion_index)
      self.list_event_suggestions.see(suggestion_index)
    browser_group = event_browser_group(event)
    if browser_group in self.group_to_events:
      group_index = self.event_group_names.index(browser_group)
      self.list_event_groups.selection_set(group_index)
      self.list_event_groups.see(group_index)
    if event in self.visible_events:
      visible_index = self.visible_events.index(event)
      self.list_events.selection_set(visible_index)
      self.list_events.see(visible_index)

    # Update the event prereq events list box
    self.list_event_prereq_events.delete(0, tk.END)
    if "triggered_by_branch" in event and len(event["triggered_by_branch"]) > 0:
      branch_event = self.events.get(event["triggered_by_branch"])
      self._insert_prerequisite(
        "🔵 Triggered by '" + event["triggered_by_branch"] + "'",
        branch_event,
      )
    
    if "chain_sources" in event and len(event["chain_sources"]) > 0:
      name = event["chain_sources"]
      source_event = self.events.get(name)
      if source_event is not None:
        name = self._event_name(
          source_event,
          bool(source_event.get("missed")),
        )

      self._insert_prerequisite(
        "🔵 Part of chain event '" + name + "' (event=" + event["chain_sources"] + ")",
        source_event,
      )

    if event_is_missable(event):
      if event.get("missed"):
        miss_summary = "🔴 Missed because: " + event.get(
          "miss_condition_text",
          "the miss condition was met",
        )
        self._insert_prerequisite(miss_summary, event)
      elif event["id"] in self.active_chain_missed_ids:
        miss_summary = "🔴 At risk in the current chain: " + event.get(
          "miss_condition_text",
          "requirements can no longer be met",
        )
        self._insert_prerequisite(miss_summary, event)
      if event.get("missed") or event["id"] in self.active_chain_missed_ids:
        for condition in event.get("miss_conditions", []):
          current_value = condition.get("saved_value")
          rule_state = "active" if condition.get("satisfied") else "inactive"
          linked_event = self.events.get(condition.get("event_id"))
          self._insert_prerequisite(
            "   " + rule_state + ": "
            + f"{condition['variable']} {condition['comparison']} {condition['value']}"
            + f" — current: {current_value!r}",
            linked_event,
          )
    
    display_conditions = [
      condition
      for condition in event.get("conditions", [])
      if not is_structural_chapter_condition(condition.get("variable"))
    ]
    unmet_count = sum(
      not condition.get("satisfied") for condition in display_conditions
    )
    if event.get("complete"):
      prerequisite_status = "completed"
    elif event.get("missed"):
      prerequisite_status = "missed"
    elif display_conditions and unmet_count == 0:
      prerequisite_status = "all requirements met"
    elif display_conditions:
      prerequisite_status = f"{unmet_count} unmet"
    else:
      prerequisite_status = "automatic/unknown trigger"
    self.label_prerequisites["text"] = (
      "Prerequisites — " + prerequisite_status
    )
    shown_conditions = display_conditions
    if self.unmet_only_var.get():
      shown_conditions = [
        condition
        for condition in display_conditions
        if not condition.get("satisfied")
      ]
    inserted_conditions = 0
    for condition in shown_conditions:
      row_text, condition_event = self._condition_row(condition, event)
      if row_text is None:
        continue
      self._insert_prerequisite(row_text, condition_event)
      inserted_conditions += 1
    if display_conditions and not inserted_conditions and self.unmet_only_var.get():
      self._insert_prerequisite("✅ All visible requirements are met.")

    if self._spoiler_hidden(event):
      self.text_code_snippets.delete(1.0, tk.END)
      self.text_code_snippets.insert(
        tk.END,
        "Spoiler mode is hiding this event's name and raw details.\n\n"
        "Disable Spoilers to reveal them.",
      )
      return

    # Restore the original raw-details view while keeping the modern parser's
    # accurate completion variable and condition evaluation.
    self.text_code_snippets.delete(1.0, tk.END)
    raw_details = (
      "event name:" + event["name"]
      + "\nevent id:" + event["id"]
      + "\nevent group:" + event["group"]
      + "\nevent chapter:" + (event.get("chapter") or "")
      + "\nevent completion variable:" + event.get("completion_variable", event["id"])
      + "\nevent miss condition:" + (event.get("miss_condition_text") or "")
      + "\nevent chain:" + (event.get("chain_sources") or "")
      + "\ntriggered by label:" + (event.get("triggered_by") or "")
      + "\ntriggered by label branch:" + (event.get("triggered_by_branch") or "")
      + "\nevent trigger file:" + str(event.get("jump_to_file") or [])
      + "\nevent trigger code:\n" + (event.get("code") or "")
    )
    self.text_code_snippets.insert(tk.END, raw_details)

    conditions = display_conditions
    if conditions:
      self.text_code_snippets.insert(tk.END, "\nconditions:")
      for condition in conditions:
        self.text_code_snippets.insert(
          tk.END,
          f'\n{"✅" if condition["satisfied"] else "❌"} '
          f'{condition["variable"]} {condition["comparison"]} {condition["value"]}',
        )

    self.text_code_snippets.insert(
      tk.END,
      "\n\n----- event code path: -----\n" + (event.get("event_rpath") or ""),
    )
    self.text_code_snippets.insert(
      tk.END,
      "\n----- full event code: -----\n" + (event.get("event_code") or ""),
    )
    self.text_code_snippets.insert(
      tk.END,
      "\n\n----- trigger code path: -----\n" + (event.get("trigger_rpath") or ""),
    )
    self.text_code_snippets.insert(
      tk.END,
      "\n\n----- full trigger code: -----\n" + (event.get("trigger_code") or ""),
    )


  def refresh(self):
    if self._refreshing:
      return False
    restore_missables = self.missable_dashboard_active
    restore_bookmarks = self.bookmark_dashboard_active
    first_refresh = not hasattr(self, "events")
    event_id_to_restore = self.active_event["id"] if self.active_event else None

    # Do not discard the currently displayed data until a reload succeeds. This
    # makes the Reload button safe when the newest save is temporarily locked.
    self._refreshing = True
    try:
      (events, save_data, characters, save_file, save_file_timestamp) = game_data.load_game_data(self.game_folder)
    except Exception as error:
      messagebox.showerror(
        "Could not reload the guide",
        "The save/game data could not be read. The current guide data was kept.\n\n"
        + str(error),
      )
      return False
    finally:
      self._refreshing = False

    normalized_save_file = (
      os.path.normcase(os.path.abspath(save_file)) if save_file else "no-save"
    )
    try:
      save_stat = os.stat(save_file) if save_file else None
      save_identity = (
        f"{save_stat.st_mtime_ns}|{save_stat.st_size}"
        if save_stat else str(save_file_timestamp)
      )
    except OSError:
      save_identity = str(save_file_timestamp)
    self.current_save_signature = normalized_save_file + "|" + save_identity
    same_saved_game = (
      first_refresh
      and self.ui_state.get("save_signature") == self.current_save_signature
    )
    if same_saved_game and not event_id_to_restore:
      event_id_to_restore = self.ui_state.get("selected_event_id")

    self.events = events
    self.bookmark_ids.intersection_update(self.events)
    self.save_data = save_data
    self.characters = sorted(characters)
    self.previous_events = []
    self.event_suggestions = []
    self.active_event = None
    self.missable_dashboard_active = False
    self.bookmark_dashboard_active = False
    self.label_events["text"] = "Event"

    # Update the save game details panel
    completed_count, total_count = event_completion_count(self.events.values())
    ready_count = sum(event.get("ready_to_trigger", False) for event in self.events.values())
    missed_count = sum(event.get("missed", False) for event in self.events.values())
    details = (
      f"Timestamp: {save_file_timestamp}\n"
      f"File: {save_file}\n\n"
      f"Completed: {completed_count}/{total_count}\n"
      f"Ready now: {ready_count}\n"
      f"Missed/skipped: {missed_count}\n"
      "Auto-watch: On"
      + (
        f" (last refresh {self._last_auto_reload_time})\n"
        if self._last_auto_reload_time
        else "\n"
      )
    )
    if game_data.last_load_warnings:
      details += "\nWarnings:\n" + "\n".join(
        "- " + warning for warning in game_data.last_load_warnings
      )
    self.text_save_details.delete(1.0, tk.END)
    self.text_save_details.insert(tk.END, details)

    # Keep the original game groups for progression suggestions, while the
    # browser splits Main into the chapter labels found in screens.rpy.
    self.group_to_events = {}
    self.suggestion_group_to_events = {}
    for id, event in self.events.items():
      game_group = event["group"]
      browser_group = event_browser_group(event)
      self.suggestion_group_to_events.setdefault(game_group, []).append(event)
      self.group_to_events.setdefault(browser_group, []).append(event)

    # Update the event groups list
    self.list_event_groups.delete(0, tk.END)
    self.event_group_names = order_event_group_names(self.group_to_events.keys())
    for event_group in self.event_group_names:
      group_completed, group_total = event_completion_count(
        self.group_to_events[event_group]
      )
      self.list_event_groups.insert(
        tk.END,
        f"{event_group}  ({group_completed}/{group_total})",
      )
    self.label_event_groups["text"] = (
      f"Event groups — Total: {completed_count}/{total_count}"
    )

    # Calculate the event suggestions
    self.list_event_suggestions.delete(0, tk.END)
    self.active_chain_events = calculate_active_chain(self.events.values())
    self.active_chain_event_ids = {
      event["id"] for event in self.active_chain_events
    }
    self.active_chain_missed_ids = {
      event["id"]
      for event in self.active_chain_events
      if chain_event_uses_missed_name(event, self.active_chain_event_ids)
    }
    self.active_chain_current_id = next(
      (
        event["id"]
        for event in self.active_chain_events
        if not event.get("missed")
      ),
      None,
    )
    chain_origin = active_chain_origin(
      self.events.values(),
      self.active_chain_events,
    )
    if self.active_chain_events and self.active_chain_current_id:
      current_index = next(
        (
          index
          for index, event in enumerate(self.active_chain_events)
          if event["id"] == self.active_chain_current_id
        ),
        0,
      )
      origin_name = self._event_name(
        chain_origin,
        bool(chain_origin and chain_origin.get("missed")),
      ) if chain_origin else "Unknown"
      self.label_suggestions["text"] = (
        f"Suggested — Chain {current_index + 1}/{len(self.active_chain_events)}\n"
        f"From: {origin_name}"
      )
    else:
      self.label_suggestions["text"] = "Suggested next events"
    self.event_suggestions = self.get_event_suggestions()
    for event in self.event_suggestions:
      in_chain = event["id"] in self.active_chain_event_ids
      show_missed_name = (
        event.get("missed")
        or event["id"] in self.active_chain_missed_ids
      )
      name = self._event_name(event, show_missed_name)
      if in_chain:
        if show_missed_name:
          icon = "⏭"
        elif event["id"] == self.active_chain_current_id:
          icon = "▶"
        else:
          icon = "↳"
        label = f'{icon} Chain — {event["group"]}: {name}'
      else:
        label = f'{event_status_icon(event)} {event["group"]}: {name}'
      self._insert_colored_row(
        self.list_event_suggestions,
        label,
        event,
      )
    if not self.event_suggestions:
      self.list_event_suggestions.insert(
        tk.END,
        "No player-triggered events are ready.",
      )

    # Restore the selected event
    if event_id_to_restore in self.events:
      self.select_event(self.events[event_id_to_restore], add_to_history=False)
    elif latest_main_event := latest_completed_main_event(self.events.values()):
      self.select_event(latest_main_event, add_to_history=False)
    elif self.event_suggestions:
      self.select_event(self.event_suggestions[0], add_to_history=False)
    else:
      first_event = next(iter(self.events.values()), None)
      self.select_event(first_event, add_to_history=False)

    # Reapply a global search/filter after reloading.
    self.on_search_changed()
    if restore_missables:
      self.button_missables()
    elif restore_bookmarks:
      self.button_bookmarks()
    if same_saved_game:
      self.root.after_idle(self._restore_ui_scroll_positions)
    return True

  def get_event_suggestions(self):
    normal_suggestions = calculate_event_suggestions(
      self.suggestion_group_to_events,
      self.characters,
    )
    suggestions = []
    seen = set()
    for event in self.active_chain_events + normal_suggestions:
      if event["id"] not in seen:
        seen.add(event["id"])
        suggestions.append(event)
    return suggestions

  def button_event_wiki(self):
    # Get the selected event name
    if self.active_event:
      # Open the webpage
      webbrowser.open(f'https://lessonsinlove.wiki/index.php?title=Special%3ASearch&search={self.active_event["name"]}&go=Go')
    else:
      # Message box
      messagebox.showinfo("No event selected", "Please select an event to view the wiki page for it.")

  def button_refresh(self):
    if self.refresh():
      self._last_seen_save_fs_signature = self._current_save_fs_signature()
      self._pending_save_fs_signature = None

  def button_latest_main(self):
    event = latest_completed_main_event(self.events.values())
    if event is None:
      messagebox.showinfo("Latest Main", "No completed Main event was found in this save.")
      return
    self._exit_dashboard_and_filters()
    self.select_event(event)

  def button_next_main(self):
    event = next_incomplete_main_event(self.events.values())
    if event is None:
      messagebox.showinfo("Next Main", "Every Main event is already completed or missed.")
      return
    self._exit_dashboard_and_filters()
    self.select_event(event)

  def button_current_chain(self):
    event = self.events.get(self.active_chain_current_id)
    if event is None:
      messagebox.showinfo("Current chain", "No automatic event chain is currently in progress.")
      return
    self._exit_dashboard_and_filters()
    self.select_event(event)

  def _exit_dashboard_and_filters(self):
    self._changing_filters = True
    self.search_var.set("")
    self.status_filter_var.set("All")
    self._changing_filters = False
    self.missable_dashboard_active = False
    self.bookmark_dashboard_active = False
    self.label_events["text"] = "Event"

  def button_missables(self):
    self._changing_filters = True
    self.search_var.set("")
    self.status_filter_var.set("All")
    self._changing_filters = False
    self.missable_dashboard_active = True
    self.bookmark_dashboard_active = False
    endangered, missed, recoverable = missable_event_sections(
      self.events.values(),
      self.active_chain_event_ids,
    )
    sections = (
      ("AT RISK", endangered),
      ("MISSED", missed),
      ("OPEN", recoverable),
    )
    self.visible_events = [
      event
      for _, section_events in sections
      for event in section_events
    ]
    self.list_events.delete(0, tk.END)
    for section_name, section_events in sections:
      for event in section_events:
        show_missed_name = section_name == "MISSED"
        name = self._event_name(event, show_missed_name)
        self._insert_colored_row(
          self.list_events,
          f"{section_name} — {event_browser_group(event)}: {name}",
          event,
        )
    self.label_events["text"] = (
      f"Miss {len(endangered)}/{len(missed)}/{len(recoverable)}"
    )
    self.list_event_groups.selection_clear(0, tk.END)
    if self.visible_events:
      self.select_event(self.visible_events[0], add_to_history=False)
      self.list_event_groups.selection_clear(0, tk.END)
    else:
      self.select_event(None, add_to_history=False)

  def button_bookmarks(self):
    self._changing_filters = True
    self.search_var.set("")
    self.status_filter_var.set("All")
    self._changing_filters = False
    self.missable_dashboard_active = False
    self.bookmark_dashboard_active = True
    self.visible_events = [
      event
      for event in self.events.values()
      if event["id"] in self.bookmark_ids
    ]
    self.list_events.delete(0, tk.END)
    for event in self.visible_events:
      self._insert_colored_row(
        self.list_events,
        f"★ {event_browser_group(event)}: {self._event_name(event, bool(event.get('missed')))}",
        event,
      )
    self.label_events["text"] = f"★ {len(self.visible_events)} saved"
    self.list_event_groups.selection_clear(0, tk.END)
    if self.visible_events:
      selected = (
        self.active_event
        if self.active_event in self.visible_events
        else self.visible_events[0]
      )
      self.select_event(selected, add_to_history=False)
      self.list_event_groups.selection_clear(0, tk.END)
    else:
      self.select_event(None, add_to_history=False)

  def button_toggle_bookmark(self):
    if self.active_event is None:
      return
    event_id = self.active_event["id"]
    if event_id in self.bookmark_ids:
      self.bookmark_ids.remove(event_id)
    else:
      self.bookmark_ids.add(event_id)
    if self.bookmark_dashboard_active:
      self.button_bookmarks()
      return
    active_event = self.active_event
    if self.missable_dashboard_active:
      self.button_missables()
    else:
      self.on_search_changed()
      self.select_event(active_event, add_to_history=False)

  def button_show_path(self):
    if self.active_event is None:
      messagebox.showinfo("Prerequisite path", "Select an event first.")
      return
    path = shortest_prerequisite_path(
      self.events.values(),
      self.active_event,
    )
    self.list_event_prereq_events.delete(0, tk.END)
    self.label_prerequisites["text"] = (
      f"Shortest prerequisite path — {len(path)} step"
      + ("s" if len(path) != 1 else "")
    )
    for index, event in enumerate(path, 1):
      name = self._event_name(event, bool(event.get("missed")))
      self._insert_prerequisite(
        f"🧭 {index}/{len(path)} {name} (event={event['id']})",
        event,
      )
    if len(path) == 1:
      self._insert_prerequisite(
        "No earlier incomplete event dependency was found; check the value requirements.",
      )

  def button_parser_health(self):
    condition_errors = [
      event
      for event in self.events.values()
      if event.get("condition_error") or event.get("miss_condition_error")
    ]
    missing_variables = sorted({
      condition["variable"]
      for event in self.events.values()
      for condition in event.get("conditions", []) + event.get("miss_conditions", [])
      if condition.get("missing")
    })
    warnings = list(game_data.last_load_warnings)
    stats = getattr(game_data, "last_load_stats", {})
    healthy = not condition_errors and not warnings
    report = [
      "Status: " + ("Healthy" if healthy else "Needs attention"),
      f"Replay events: {len(self.events)}",
      f"Ren'Py files scanned: {stats.get('script_files', 'unknown')}",
      "Static parser cache: " + (
        "reused" if stats.get("cache_hit") else "rebuilt"
      ),
      f"Unsupported conditions: {len(condition_errors)}",
      f"Missing save variables: {len(missing_variables)} (usually future/optional routes)",
    ]
    if missing_variables:
      report.append("\nMissing variables:\n- " + "\n- ".join(missing_variables[:20]))
      if len(missing_variables) > 20:
        report.append(f"\n...and {len(missing_variables) - 20} more")
    if warnings:
      report.append("\nWarnings:\n- " + "\n- ".join(warnings))
    messagebox.showinfo("Parser health", "\n".join(report))

  def on_spoiler_mode_changed(self):
    if hasattr(self, "events"):
      self.refresh()

  def on_unmet_only_changed(self):
    if self.active_event is not None:
      self.select_event(self.active_event, add_to_history=False)

  def focus_search(self, _event=None):
    self.search_entry.focus_set()
    self.search_entry.selection_range(0, tk.END)
    return "break"

  def keyboard_reload(self, _event=None):
    self.button_refresh()
    return "break"

  def keyboard_back(self, _event=None):
    self.button_back()
    return "break"

  def keyboard_latest_main(self, _event=None):
    self.button_latest_main()
    return "break"

  def keyboard_next_main(self, _event=None):
    self.button_next_main()
    return "break"

  def keyboard_current_chain(self, _event=None):
    self.button_current_chain()
    return "break"

  def keyboard_toggle_bookmark(self, _event=None):
    self.button_toggle_bookmark()
    return "break"

  def keyboard_bookmarks(self, _event=None):
    self.button_bookmarks()
    return "break"

  def keyboard_clear_filters(self, _event=None):
    self._exit_dashboard_and_filters()
    if self.active_event is not None:
      self._populate_event_list(
        self.group_to_events[event_browser_group(self.active_event)]
      )
      self.select_event(self.active_event, add_to_history=False)
    return "break"


  def button_back(self):
    self.previous_event()


  def button_forward(self):
    print("command")

  def on_list_event_suggestions_select(self, value):
    # Get the selected event
    selection = self.list_event_suggestions.curselection()
    if len(selection) == 0:
      return
    if selection[0] >= len(self.event_suggestions):
      return
    event = self.event_suggestions[selection[0]]

    self.select_event(event)

  def on_list_event_groups_select(self, value):
    # Get the selected event group
    selection = self.list_event_groups.curselection()
    if len(selection) == 0:
      return
    if selection[0] >= len(self.event_group_names):
      return
    event_group = self.event_group_names[selection[0]]

    # Selecting a group exits the global search and focuses its progression
    # frontier: the first event after the latest completed/missed event.
    self._exit_dashboard_and_filters()
    group_events = self.group_to_events[event_group]
    last_progress = max(
      (
        index
        for index, event in enumerate(group_events)
        if event.get("complete") or event.get("missed")
      ),
      default=-1,
    )
    focused_event = group_events[min(last_progress + 1, len(group_events) - 1)]

    self.select_event(focused_event)
  
  def on_list_events_select(self, value):
    # Get the selected event
    selection = self.list_events.curselection()
    if len(selection) == 0:
      return
    if selection[0] >= len(self.visible_events):
      return
    event = self.visible_events[selection[0]]

    # Select the event
    self.select_event(event)

  def on_list_event_prereq_events_select(self, value):
    # Parse a possible selected event from the selected row
    # Text is like "..... (event=EVENT_ID)"
    selection = self.list_event_prereq_events.curselection()
    if len(selection) == 0:
      return
    text = self.list_event_prereq_events.get(selection[0])
    if text.find("(event=") == -1:
      return

    # Get the event id
    event_id = text[text.find("(event=") + 7:]
    event_id = event_id[:event_id.find(")")]
    if event_id not in self.events:
      # Event not found
      print(f"ERROR: Referenced event not found: {event_id}")
      return
    
    # Select the event
    self.select_event(self.events[event_id])
      

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
