import unittest

import game_data

from main import (
  App,
  INVITE_EVENT_COLOR,
  LUST_EVENT_COLOR,
  MISSABLE_EVENT_COLOR,
  active_chain_origin,
  calculate_active_chain,
  calculate_event_suggestions,
  chain_event_uses_missed_name,
  event_browser_group,
  event_completion_count,
  event_display_color,
  event_name_for_display,
  is_structural_chapter_condition,
  latest_completed_main_event,
  missable_event_sections,
  next_incomplete_main_event,
  order_event_group_names,
  shortest_prerequisite_path,
)


def event(event_id, *, complete=False, missed=False, ready=False, **extra):
  value = {
    "id": event_id,
    "complete": complete,
    "missed": missed,
    "ready_to_trigger": ready,
  }
  value.update(extra)
  return value


class EventSuggestionTests(unittest.TestCase):
  def test_unmet_requirement_explains_the_current_save_value(self):
    app = App.__new__(App)
    app.events = {}
    selected_event = {
      "id": "target",
      "completion_variable": "target_done",
    }

    row, linked_event = app._condition_row(
      {
        "variable": "miku_love",
        "comparison": ">=",
        "value": 25,
        "saved_value": 18,
        "satisfied": False,
      },
      selected_event,
    )

    self.assertEqual(
      row,
      "❌Miku love greater than or equal to 25 — current: 18",
    )
    self.assertIsNone(linked_event)

  def test_save_watcher_reloads_after_a_signature_is_seen_twice(self):
    app = App.__new__(App)
    app._save_watch_job = None
    app._last_seen_save_fs_signature = ("old",)
    app._pending_save_fs_signature = ("new",)
    app._refreshing = False
    app._last_auto_reload_time = None
    app._current_save_fs_signature = lambda: ("new",)
    refresh_calls = []
    app.refresh = lambda: refresh_calls.append(True) or True
    app._schedule_save_watch = lambda: None
    previous_warnings = game_data.last_load_warnings
    game_data.last_load_warnings = []
    try:
      app._watch_save_folder()
    finally:
      game_data.last_load_warnings = previous_warnings

    self.assertEqual(refresh_calls, [True])
    self.assertEqual(app._last_seen_save_fs_signature, ("new",))

  def test_completion_counter_reports_completed_and_total(self):
    self.assertEqual(
      event_completion_count([
        event("one", complete=True),
        event("two", missed=True),
        event("three"),
      ]),
      (1, 3),
    )

  def test_each_replay_entry_has_its_own_count(self):
    self.assertEqual(
      event_completion_count([
        event("bucketscene", complete=True),
        event("mothersmilk", complete=True),
        event("amyevent", complete=True),
        event("kirinspecial30", complete=True),
        event("kirinlust202", complete=False),
        event("ordinary", complete=True),
      ]),
      (5, 6),
    )

  def test_main_events_are_split_by_parsed_chapter_for_browsing(self):
    self.assertEqual(
      event_browser_group({"group": "Main", "chapter": "Chapter 3"}),
      "Main — Chapter 3",
    )
    self.assertEqual(event_browser_group({"group": "Ami"}), "Ami")

  def test_all_main_chapters_are_ordered_before_character_groups(self):
    self.assertEqual(
      order_event_group_names([
        "Main — Chapter 1",
        "Ami",
        "Main — Chapter 3",
        "Chika",
        "Main — Chapter 2",
        "Main — Chapter 4",
      ]),
      [
        "Main — Chapter 1",
        "Main — Chapter 2",
        "Main — Chapter 3",
        "Main — Chapter 4",
        "Ami",
        "Chika",
      ],
    )

  def test_chapter_activation_is_hidden_from_event_prerequisites(self):
    self.assertTrue(is_structural_chapter_condition("chap4active"))
    self.assertTrue(is_structural_chapter_condition("chapter_active"))
    self.assertFalse(is_structural_chapter_condition("beachseven1"))

  def test_fresh_launch_selects_the_latest_completed_main_event(self):
    latest = event("main-latest", complete=True, group="Main")
    events = [
      event("main-old", complete=True, group="Main"),
      event("ami-newer", complete=True, group="Ami"),
      latest,
      event("main-next", group="Main"),
    ]

    self.assertIs(latest_completed_main_event(events), latest)

  def test_fresh_launch_has_no_default_when_main_has_no_completion(self):
    self.assertIsNone(latest_completed_main_event([
      event("main-next", group="Main"),
      event("ami-done", complete=True, group="Ami"),
    ]))

  def test_next_main_starts_after_latest_progress(self):
    expected = event("next", group="Main")
    events = [
      event("done", complete=True, group="Main"),
      event("missed", missed=True, group="Main"),
      expected,
      event("later", group="Main"),
    ]

    self.assertIs(next_incomplete_main_event(events), expected)

  def test_shortest_prerequisite_path_walks_unfinished_dependencies(self):
    root = event("root")
    middle = event("middle", required_events=["root"])
    target = event("target", required_events=["middle"])

    path = shortest_prerequisite_path([root, middle, target], target)

    self.assertEqual([item["id"] for item in path], ["root", "middle", "target"])

  def test_shortest_prerequisite_path_skips_completed_dependencies(self):
    done = event("done", complete=True)
    target = event("target", required_events=["done"])

    self.assertEqual(shortest_prerequisite_path([done, target], target), [target])

  def test_active_chain_includes_missed_context_current_and_future_events(self):
    root = event("root", complete=True)
    missed = event(
      "missed",
      missed=True,
      chain_sources="root",
      miss_condition_text="route_closed",
    )
    current = event("current", chain_sources="missed")
    future = event("future", chain_sources="current")

    chain = calculate_active_chain([root, missed, current, future])

    self.assertEqual(
      [item["id"] for item in chain],
      ["missed", "current", "future"],
    )

  def test_active_chain_can_show_an_unavoidable_missed_title(self):
    missable = event(
      "missable",
      miss_condition_text="route_closed",
      missed_name="Lost Chance",
      requirements_satisfied=False,
    )

    self.assertTrue(chain_event_uses_missed_name(missable, {"missable"}))
    self.assertFalse(chain_event_uses_missed_name(missable, set()))
    self.assertEqual(
      event_name_for_display(missable, True),
      "Lost Chance",
    )

  def test_active_chain_origin_walks_back_to_the_completed_source(self):
    root = event("root", complete=True)
    middle = event("middle", missed=True, chain_sources="root")
    current = event("current", chain_sources="middle")

    self.assertIs(
      active_chain_origin([root, middle, current], [middle, current]),
      root,
    )

  def test_missable_dashboard_sections_events_by_save_state(self):
    endangered = event(
      "risk",
      miss_condition_text="closed",
      requirements_satisfied=False,
    )
    missed = event("lost", missed=True, miss_condition_text="closed")
    recoverable = event("open", miss_condition_text="closed")
    completed = event("done", complete=True, miss_condition_text="closed")

    sections = missable_event_sections(
      [endangered, missed, recoverable, completed],
      {"risk"},
    )

    self.assertEqual(
      [[item["id"] for item in section] for section in sections],
      [["risk"], ["lost"], ["open"]],
    )

  def test_event_colors_match_game_categories(self):
    self.assertEqual(
      event_display_color(event("missable", miss_condition_text="miss")),
      MISSABLE_EVENT_COLOR,
    )
    self.assertEqual(
      event_display_color(event("invite", category="invite")),
      INVITE_EVENT_COLOR,
    )
    self.assertEqual(
      event_display_color(event("lust", category="lust")),
      LUST_EVENT_COLOR,
    )

  def test_progression_frontier_has_no_negative_index_wraparound(self):
    first = event("first", ready=True)
    second = event("second")

    suggestions = calculate_event_suggestions(
      {"Ami": [first, second]},
      ["Ami"],
    )

    self.assertEqual([item["id"] for item in suggestions], ["first"])

  def test_missed_events_advance_progress_and_automatic_chains_are_hidden(self):
    next_event = event("next", ready=True)
    later_event = event("later", ready=True)
    suggestions = calculate_event_suggestions(
      {
        "Ami": [
          event("done", complete=True),
          event("skipped", missed=True),
          event("automatic", ready=True, chain_sources="done"),
          next_event,
          later_event,
        ],
      },
      ["Ami"],
    )

    self.assertEqual(
      [item["id"] for item in suggestions],
      ["next", "later"],
    )

  def test_ready_branch_events_are_suggested(self):
    suggestion = event("branch", ready=True, triggered_by_branch="weekendhub")

    suggestions = calculate_event_suggestions(
      {"Ami": [event("done", complete=True), suggestion]},
      ["Ami"],
    )

    self.assertEqual([item["id"] for item in suggestions], ["branch"])

  def test_main_group_only_suggests_one_event(self):
    suggestions = calculate_event_suggestions(
      {
        "Main": [
          event("done", complete=True),
          event("next", ready=True),
          event("also-ready", ready=True),
        ],
      },
      [],
    )

    self.assertEqual([item["id"] for item in suggestions], ["next"])


if __name__ == "__main__":
  unittest.main()
