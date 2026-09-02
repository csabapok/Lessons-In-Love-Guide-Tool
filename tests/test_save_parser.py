import pickle
import os
import tempfile
import unittest
import zipfile

import game_data


class ParseSaveLogTests(unittest.TestCase):
  def test_protocol_2_memoized_store_values(self):
    save = pickle.dumps(
      {
        "store.completed": True,
        "store.incomplete": False,
        "store.points": 513,
        "store.custom_name": "Rin",
        "not_a_store_value": True,
      },
      protocol=2,
    )

    self.assertEqual(
      game_data.parse_save_log(save),
      {
        "completed": True,
        "incomplete": False,
        "points": 513,
        "custom_name": "Rin",
      },
    )

  def test_protocol_4_short_unicode_store_values(self):
    save = pickle.dumps(
      {"store.event_done": True, "store.day": 7},
      protocol=4,
    )

    self.assertEqual(
      game_data.parse_save_log(save),
      {"event_done": True, "day": 7},
    )

  def test_complex_values_are_not_unpickled(self):
    save = pickle.dumps(
      {"store.history": ["not", "needed"], "store.event_done": True},
      protocol=2,
    )

    self.assertEqual(
      game_data.parse_save_log(save),
      {"event_done": True},
    )

  def test_reads_requested_persistent_field_before_changed_timestamp(self):
    persistent = pickle.dumps(
      {
        "alexisevent": True,
        "_changed": {"alexisevent": 1730761208.466065},
      },
      protocol=2,
    )

    self.assertEqual(
      game_data.parse_persistent_data(persistent, {"alexisevent"}),
      {"persistent.alexisevent": True},
    )

  def test_screen_completion_flags_and_alternate_replays(self):
    screens = '''
screen mikutracker():
    use game_menu(_("Miku Events"), scroll="viewport"):
        if firsttimesoccerfield == True:
            textbutton _("Daytime Stalking Pass {b}✓{/b}"):
                text_style "mybutton"
                action Replay("firsttimesoccer", locked=False)

screen saratracker():
    use game_menu(_("Sara Events"), scroll="viewport"):
        if saralust20 == True:
            if bonus == True:
                textbutton _("Engulfed {b}✓{/b}"):
                    text_style "mybutton"
                    action Replay("saralust20x", locked=False)
            else:
                textbutton _("Engulfed {b}✓{/b}"):
                    text_style "mybutton"
                    action Replay("saralust20intro", locked=False)

screen secrettracker():
    use game_menu(_("HAPPY SCENES"), scroll="viewport"):
        if persistent.alexisevent == True:
            textbutton _("Alexisthymia {b}✓{/b}"):
                text_style "mybutton"
                action Replay("alexisevent", locked=False)
'''

    events = game_data.parse_screen_events(screens)

    self.assertEqual(
      events["firsttimesoccer"]["completion_variable"],
      "firsttimesoccerfield",
    )
    engulfed = [event for event in events.values() if event["name"] == "Engulfed"]
    self.assertEqual(len(engulfed), 1)
    self.assertEqual(engulfed[0]["completion_variable"], "saralust20")
    self.assertEqual(
      events["alexisevent"]["completion_variable"],
      "persistent.alexisevent",
    )

  def test_condition_evaluator_preserves_or_parentheses_and_strings(self):
    result, details, error = game_data.evaluate_condition(
      'day == 4 and (first_path == True or missed_path == True) '
      'and secretlottery == "157842"',
      {
        "day": 4,
        "first_path": False,
        "missed_path": True,
        "secretlottery": "157842",
      },
    )

    self.assertTrue(result)
    self.assertIsNone(error)
    self.assertEqual(len(details), 4)
    self.assertTrue(details[-1]["satisfied"])

  def test_condition_evaluator_never_executes_calls(self):
    result, _, error = game_data.evaluate_condition("dangerous_call()", {})

    self.assertIsNone(result)
    self.assertIsNotNone(error)

  def test_condition_evaluator_marks_values_missing_from_the_save(self):
    result, details, error = game_data.evaluate_condition(
      "future_event == True",
      {},
    )

    self.assertFalse(result)
    self.assertIsNone(error)
    self.assertTrue(details[0]["missing"])

  def test_missable_evaluation_keeps_the_reason_and_current_value(self):
    events = {
      "missable": {
        "completion_variable": "missable_done",
        "miss_condition_text": "route_closed == True",
        "trigger_conditions": [],
        "additional_conditions": [],
      }
    }

    game_data.apply_save_state(events, {"route_closed": True})

    self.assertTrue(events["missable"]["missed"])
    self.assertEqual(
      events["missable"]["miss_conditions"][0]["saved_value"],
      True,
    )

  def test_nested_trigger_conditions_are_combined(self):
    lines = [
      "label hub:",
      "    if chapter_active == True:",
      "        menu:",
      '            "Go":',
      "                if day == 4 and event_done == False:",
      "                    jump targetevent",
    ]

    expression, line_index = game_data.find_trigger_condition(lines, 5)

    self.assertEqual(
      expression,
      "(chapter_active == True) and (day == 4 and event_done == False)",
    )
    self.assertEqual(line_index, 1)

  def test_concise_trigger_code_only_contains_the_selected_event(self):
    lines = [
      "label hub:",
      "    if chap4active == True:",
      "        if day == 2 and earlier == False:",
      "            jump earlier",
      "        if day == 4 and target_done == False:",
      "            jump target",
    ]

    code = game_data.concise_trigger_code(lines, 5)

    self.assertEqual(
      code,
      "if day == 4 and target_done == False:\njump target",
    )

  def test_only_struck_out_screen_branches_count_as_missed(self):
    screens = '''
screen maintracker():
    use game_menu(_("Main Events"), scroll="viewport"):
        if regular_done == True:
            textbutton _("Regular {b}✓{/b}"):
                action Replay("regular", locked=False)
        elif bonus == True:
            text _("Regular alternate title")
        else:
            text _("???")
        if missable_done == True:
            textbutton _("Missable {b}✓{/b}"):
                action Replay("missable", locked=False)
        elif route_closed == True:
            text _("{color=EF1A1A}{s}Missed{/s}{/color}")
        else:
            text _("???")
'''

    events = game_data.parse_screen_events(screens)

    self.assertIsNone(events["regular"]["miss_condition_text"])
    self.assertEqual(
      events["missable"]["miss_condition_text"],
      "route_closed == True",
    )
    self.assertEqual(events["missable"]["missed_name"], "Missed")

  def test_replay_colors_identify_invite_and_lust_events(self):
    screens = '''
screen amitracker():
    use game_menu(_("Ami Events"), scroll="viewport"):
        if invite_done == True:
            textbutton _("Invite Event {b}✓{/b}"):
                action Replay("amiinvite1", locked=False)
        else:
            text _("{color=778EFF}Invite Event{/color}")
        if lust_done == True:
            textbutton _("Lust Event {b}✓{/b}"):
                action Replay("amilust10", locked=False)
        else:
            text _("{color=FF85FD}Lust Event{/color}")
'''

    events = game_data.parse_screen_events(screens)

    self.assertEqual(events["amiinvite1"]["category"], "invite")
    self.assertEqual(events["amilust10"]["category"], "lust")

  def test_main_replay_events_keep_their_chapter_label(self):
    screens = '''
screen maintracker():
    use game_menu(_("Main Events"), scroll="viewport"):
        vbox:
            label "Chapter 1"
            if first_done == True:
                textbutton _("First {b}✓{/b}"):
                    action Replay("first", locked=False)

screen maintrackerch2():
    use game_menu(_("Main Events"), scroll="viewport"):
        vbox:
            label "Chapter 2"
            if second_done == True:
                textbutton _("Second {b}✓{/b}"):
                    action Replay("second", locked=False)
'''

    events = game_data.parse_screen_events(screens)

    self.assertEqual(events["first"]["chapter"], "Chapter 1")
    self.assertEqual(events["second"]["chapter"], "Chapter 2")

  def test_latest_save_falls_back_to_previous_readable_file(self):
    with tempfile.TemporaryDirectory() as folder:
      valid_path = os.path.join(folder, "older.save")
      broken_path = os.path.join(folder, "newer.save")
      with zipfile.ZipFile(valid_path, "w") as save_zip:
        save_zip.writestr(
          "log",
          pickle.dumps({"store.completed": True}, protocol=4),
        )
      with open(broken_path, "wb") as broken_file:
        broken_file.write(b"not a zip")
      os.utime(valid_path, (100, 100))
      os.utime(broken_path, (200, 200))

      save_path, values, warnings = game_data.load_latest_save(folder)

      self.assertEqual(save_path, valid_path)
      self.assertEqual(values, {"completed": True})
      self.assertEqual(len(warnings), 1)
      self.assertIn("newer.save", warnings[0])


if __name__ == "__main__":
  unittest.main()
