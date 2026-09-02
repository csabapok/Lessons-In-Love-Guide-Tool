# Import Module
import ast
import copy
import datetime
import glob
from itertools import groupby
import re
from tkinter import *
import os
import pickletools
from tkinter import filedialog
import zipfile
import sys
import zlib


_PICKLE_MEMO_WRITE_OPS = {"PUT", "BINPUT", "LONG_BINPUT", "MEMOIZE"}
_PICKLE_MEMO_READ_OPS = {"GET", "BINGET", "LONG_BINGET"}
_PICKLE_PRIMITIVE_OPS = {
  "INT", "BININT", "BININT1", "BININT2", "LONG", "LONG1", "LONG4",
  "FLOAT", "BINFLOAT",
  "STRING", "BINSTRING", "SHORT_BINSTRING",
  "UNICODE", "BINUNICODE", "SHORT_BINUNICODE", "BINUNICODE8",
  "BINBYTES", "SHORT_BINBYTES", "BINBYTES8", "BYTEARRAY8",
}
_UNSUPPORTED_PICKLE_VALUE = object()
_SCREEN_TRUE_CONDITION = re.compile(
  r"^(?:if|elif)\s+([A-Za-z_][A-Za-z0-9_.]*)(?:\s*==\s*True)?\s*:$"
)
_NON_EVENT_COMPLETION_VARIABLES = {"bonus"}
_MISSING_VALUE = object()
_TEXT_FILE_CACHE = {}
_GAME_STRUCTURE_CACHE = {}
last_load_warnings = []
last_load_stats = {}


def read_text_cached(path):
  """Reads UTF-8 game text and reuses it until the file changes."""
  stat = os.stat(path)
  signature = (stat.st_mtime_ns, stat.st_size)
  cached = _TEXT_FILE_CACHE.get(path)
  if cached is not None and cached[0] == signature:
    return cached[1]

  with open(path, "r", encoding="utf8") as file:
    text = file.read()
  _TEXT_FILE_CACHE[path] = (signature, text)
  return text


def discover_script_files(game_folder):
  """Returns every Ren'Py source file, preferring core files over add-ons."""
  game_path = os.path.join(game_folder, "game")
  files = glob.glob(os.path.join(game_path, "**", "*.rpy"), recursive=True)
  files = list(dict.fromkeys(os.path.normpath(path) for path in files))
  return sorted(
    files,
    key=lambda path: (
      os.path.relpath(path, game_path).count(os.sep),
      os.path.relpath(path, game_path).lower(),
    ),
  )


def _dotted_name(node):
  if isinstance(node, ast.Name):
    return node.id
  if isinstance(node, ast.Attribute):
    parent = _dotted_name(node.value)
    if parent is not None:
      return parent + "." + node.attr
  return None


def _default_for_comparison(value):
  if isinstance(value, bool):
    return False
  if isinstance(value, (int, float)):
    return 0
  if isinstance(value, str):
    return ""
  if isinstance(value, (list, tuple, set, dict)):
    return type(value)()
  return None


def _comparison_symbol(operator):
  return {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.In: "in",
    ast.NotIn: "not in",
    ast.Is: "is",
    ast.IsNot: "is not",
  }.get(type(operator))


def _apply_comparison(operator, left, right):
  if isinstance(operator, ast.Eq):
    return left == right
  if isinstance(operator, ast.NotEq):
    return left != right
  if isinstance(operator, ast.Gt):
    return left > right
  if isinstance(operator, ast.GtE):
    return left >= right
  if isinstance(operator, ast.Lt):
    return left < right
  if isinstance(operator, ast.LtE):
    return left <= right
  if isinstance(operator, ast.In):
    return left in right
  if isinstance(operator, ast.NotIn):
    return left not in right
  if isinstance(operator, ast.Is):
    return left is right
  if isinstance(operator, ast.IsNot):
    return left is not right
  raise ValueError("Unsupported comparison operator")


def evaluate_condition(expression, values):
  """
  Safely evaluates the Python-like subset Ren'Py uses for event conditions.

  Returns ``(result, details, error)``. Details contain the individual
  comparisons used by the UI; no game code or function calls are executed.
  """
  details = []

  def resolve(node):
    variable = _dotted_name(node)
    if variable is not None:
      return values.get(variable, _MISSING_VALUE)
    if isinstance(node, ast.Constant):
      return node.value
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
      resolved = [resolve(item) for item in node.elts]
      if any(item is _MISSING_VALUE for item in resolved):
        return _MISSING_VALUE
      if isinstance(node, ast.Tuple):
        return tuple(resolved)
      if isinstance(node, ast.Set):
        return set(resolved)
      return resolved
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
      value = resolve(node.operand)
      return -value if value is not _MISSING_VALUE else value
    if isinstance(node, ast.BinOp):
      left = resolve(node.left)
      right = resolve(node.right)
      if left is _MISSING_VALUE or right is _MISSING_VALUE:
        return _MISSING_VALUE
      if isinstance(node.op, ast.Add):
        return left + right
      if isinstance(node.op, ast.Sub):
        return left - right
      if isinstance(node.op, ast.Mult):
        return left * right
      if isinstance(node.op, ast.Div):
        return left / right
      if isinstance(node.op, ast.Mod):
        return left % right
    raise ValueError("Unsupported value in condition")

  def evaluate(node):
    if isinstance(node, ast.BoolOp):
      results = [evaluate(value) for value in node.values]
      if isinstance(node.op, ast.And):
        return all(results)
      if isinstance(node.op, ast.Or):
        return any(results)
      raise ValueError("Unsupported boolean operator")

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
      variable = _dotted_name(node.operand)
      if variable is not None:
        saved_value = values.get(variable, False)
        satisfied = not bool(saved_value)
        details.append({
          "variable": variable,
          "comparison": "==",
          "value": False,
          "saved_value": saved_value,
          "satisfied": satisfied,
          "missing": variable not in values,
        })
        return satisfied
      return not evaluate(node.operand)

    if isinstance(node, ast.Compare):
      left_node = node.left
      left_value = resolve(left_node)
      result = True
      for operator, right_node in zip(node.ops, node.comparators):
        right_value = resolve(right_node)
        left_missing = left_value is _MISSING_VALUE
        right_missing = right_value is _MISSING_VALUE
        if left_value is _MISSING_VALUE:
          left_value = _default_for_comparison(right_value)
        if right_value is _MISSING_VALUE:
          right_value = _default_for_comparison(left_value)
        try:
          comparison_result = _apply_comparison(operator, left_value, right_value)
        except (TypeError, ValueError):
          comparison_result = False

        variable = _dotted_name(left_node)
        comparison_value = right_value
        saved_value = left_value
        if variable is None:
          variable = _dotted_name(right_node)
          comparison_value = left_value
          saved_value = right_value
          variable_missing = right_missing
        else:
          variable_missing = left_missing

        details.append({
          "variable": variable or ast.unparse(left_node),
          "comparison": _comparison_symbol(operator) or "?",
          "value": comparison_value,
          "saved_value": saved_value,
          "satisfied": comparison_result,
          "missing": variable_missing,
        })
        result = result and comparison_result
        left_node = right_node
        left_value = right_value
      return result

    variable = _dotted_name(node)
    if variable is not None:
      saved_value = values.get(variable, False)
      satisfied = bool(saved_value)
      details.append({
        "variable": variable,
        "comparison": "==",
        "value": True,
        "saved_value": saved_value,
        "satisfied": satisfied,
        "missing": variable not in values,
      })
      return satisfied

    if isinstance(node, ast.Constant):
      return bool(node.value)
    raise ValueError("Unsupported expression in condition")

  try:
    tree = ast.parse(expression.strip(), mode="eval")
    return bool(evaluate(tree.body)), details, None
  except (SyntaxError, TypeError, ValueError, ZeroDivisionError) as error:
    return None, details, str(error)


def _condition_from_header(line):
  match = re.match(r"^(?:if|elif)\s+(.+?)\s*:\s*(?:#.*)?$", line.strip())
  if match:
    return match.group(1).strip()
  return None


def _is_plain_incomplete_branch(expression, completion_variable):
  compact = re.sub(r"\s+", "", expression)
  return compact in {
    completion_variable + "==False",
    "not" + completion_variable,
  }


def find_trigger_condition(lines, jump_index):
  """Finds all enclosing Ren'Py if/elif conditions for a jump."""
  jump_line = lines[jump_index]
  jump_indentation = len(jump_line) - len(jump_line.lstrip())
  parent_indentation = jump_indentation
  conditions = []
  first_condition_line = None

  # Moving backwards, the nearest preceding block header at every lower
  # indentation level is an ancestor of the jump. This catches hub layouts
  # such as ``if chapter_active: if day == ...: jump event`` without confusing
  # sibling branches for parents.
  for line_index in range(jump_index - 1, -1, -1):
    raw_line = lines[line_index]
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
      continue
    indentation = len(raw_line) - len(raw_line.lstrip())
    if indentation >= parent_indentation:
      continue

    # Only block-opening lines can be parents. A menu/choice/while block still
    # lowers the ceiling so an outer if can be found.
    if stripped.endswith(":"):
      parent_indentation = indentation
      condition = _condition_from_header(stripped)
      if condition is not None:
        conditions.append(condition)
        first_condition_line = line_index

    if stripped.startswith("label ") and indentation == 0:
      break

  if not conditions:
    return None, None
  conditions.reverse()
  if len(conditions) == 1:
    return conditions[0], first_condition_line
  return "(" + ") and (".join(conditions) + ")", first_condition_line


def concise_trigger_code(lines, jump_index):
  """Returns only the nearest conditional header and selected event jump."""
  jump_line = lines[jump_index]
  parent_indentation = len(jump_line) - len(jump_line.lstrip())

  for line_index in range(jump_index - 1, -1, -1):
    raw_line = lines[line_index]
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
      continue
    indentation = len(raw_line) - len(raw_line.lstrip())
    if indentation >= parent_indentation:
      continue

    if stripped.endswith(":"):
      parent_indentation = indentation
      if _condition_from_header(stripped) is not None:
        return stripped + "\n" + jump_line.strip()

    if stripped.startswith("label ") and indentation == 0:
      break

  return jump_line.strip()


def _looks_like_missed_screen_branch(lines, branch_index, indentation):
  """Uses the game's red strikethrough replay entry as the missed marker."""
  branch_lines = []
  for raw_line in lines[branch_index + 1:]:
    stripped = raw_line.strip()
    line_indentation = len(raw_line) - len(raw_line.lstrip())
    if stripped and line_indentation <= indentation:
      break
    branch_lines.append(stripped.lower())
  branch_text = "\n".join(branch_lines)
  return "{s}" in branch_text or "strikethrough" in branch_text


def _screen_text_name(line):
  """Extracts a plain event title from a Ren'Py translated text line."""
  match = re.search(r'text\s+_\("(.*?)"\)', line)
  if match is None:
    return None
  return re.sub(r"\{.*?\}", "", match.group(1)).strip()


def _missed_screen_name(lines, branch_index, indentation):
  for raw_line in lines[branch_index + 1:]:
    stripped = raw_line.strip()
    line_indentation = len(raw_line) - len(raw_line.lstrip())
    if stripped and line_indentation <= indentation:
      break
    if "{s}" in stripped or "strikethrough" in stripped.lower():
      return _screen_text_name(stripped)
  return None


def _screen_event_category(lines, textbutton_index, condition_indentation):
  """Reads the invite/lust color used by the game's locked replay title."""
  for raw_line in lines[textbutton_index + 1:]:
    stripped = raw_line.strip()
    indentation = len(raw_line) - len(raw_line.lstrip())
    if (
      stripped.startswith("if ")
      and indentation <= condition_indentation
    ):
      break
    lowered = stripped.lower().replace("#", "")
    if "{color=778eff}" in lowered:
      return "invite"
    if "{color=ff85fd}" in lowered:
      return "lust"
  return None


def _primitive_pickle_value(opcode_name, argument):
  """Returns a primitive represented by a pickle opcode without unpickling."""
  if opcode_name == "NONE":
    return None
  if opcode_name == "NEWTRUE":
    return True
  if opcode_name == "NEWFALSE":
    return False
  if opcode_name in _PICKLE_PRIMITIVE_OPS:
    return argument
  return _UNSUPPORTED_PICKLE_VALUE


def _parse_pickle_primitive_values(save, key_from_primitive, expected_keys=None):
  """Safely extracts selected primitive values from a pickle opcode stream."""
  values = {}
  memo = {}
  last_primitive = _UNSUPPORTED_PICKLE_VALUE
  pending_name = None

  for opcode, argument, _ in pickletools.genops(save):
    opcode_name = opcode.name

    # Pickle commonly memoizes a store key between the key and its value. The
    # previous parser treated this memo opcode as the value and lost every key.
    if opcode_name in _PICKLE_MEMO_WRITE_OPS:
      if opcode_name == "MEMOIZE":
        memo_index = len(memo)
      else:
        memo_index = int(argument)
      memo[memo_index] = last_primitive
      continue

    if opcode_name in _PICKLE_MEMO_READ_OPS:
      primitive = memo.get(int(argument), _UNSUPPORTED_PICKLE_VALUE)
    else:
      primitive = _primitive_pickle_value(opcode_name, argument)

    if pending_name is not None:
      if (
        primitive is not _UNSUPPORTED_PICKLE_VALUE
        and pending_name not in values
      ):
        values[pending_name] = primitive
        if expected_keys is not None and len(values) >= expected_keys:
          break
      pending_name = None
      last_primitive = primitive
      continue

    last_primitive = primitive
    if isinstance(primitive, str):
      pending_name = key_from_primitive(primitive)

  return values


def parse_save_log(save):
  """
  Extract primitive ``store.*`` variables from a Ren'Py save log.

  Ren'Py saves are pickles containing many game-specific objects. Unpickling one
  in this standalone tool would both require Ren'Py and execute pickle reducers,
  so this walks the pickle opcodes instead. It supports both the older compact
  string opcodes and the memoized BINUNICODE keys emitted by newer Ren'Py.
  """
  def store_key(value):
    if value.startswith("store.") and value[6:].isidentifier():
      return value[6:]
    return None

  return _parse_pickle_primitive_values(save, store_key)


def parse_persistent_data(save, fields):
  """Extracts requested primitive fields from a decompressed persistent pickle."""
  fields = set(fields)
  if not fields:
    return {}

  def persistent_key(value):
    if value in fields:
      return "persistent." + value
    return None

  return _parse_pickle_primitive_values(
    save,
    persistent_key,
    expected_keys=len(fields),
  )


def _screen_condition_variable(line):
  match = _SCREEN_TRUE_CONDITION.match(line)
  if match:
    return match.group(1)
  return None


def _choose_completion_variable(condition_blocks, replay_id):
  candidates = [
    variable
    for _, variable in condition_blocks
    if variable is not None
    and variable not in _NON_EVENT_COMPLETION_VARIABLES
  ]
  if not candidates:
    return replay_id

  def similarity(variable):
    variable = variable.removeprefix("persistent.")
    return len(os.path.commonprefix([variable, replay_id]))

  return max(candidates, key=similarity)


def parse_screen_events(script):
  """Parses replay events and their actual completion flags from screens.rpy."""
  events = {}
  logical_event_keys = set()
  condition_blocks = []
  last_event_by_condition_indent = {}
  lines = script.split("\n")
  current_event_group = None
  current_event_chapter = None

  for i, raw_line in enumerate(lines):
    line = raw_line.strip()
    indentation = len(raw_line) - len(raw_line.lstrip())

    if line.startswith("screen ") and indentation == 0:
      current_event_group = None
      current_event_chapter = None
      condition_blocks = []
      last_event_by_condition_indent = {}

    if line and not line.startswith("#"):
      while condition_blocks and indentation <= condition_blocks[-1][0]:
        condition_blocks.pop()

      if line.startswith("if "):
        condition_blocks.append((indentation, _screen_condition_variable(line)))
      elif line.startswith("elif "):
        previous_event_id = last_event_by_condition_indent.get(indentation)
        miss_expression = _condition_from_header(line)
        if (
          previous_event_id is not None
          and miss_expression is not None
          and _looks_like_missed_screen_branch(lines, i, indentation)
        ):
          previous_event = events[previous_event_id]
          if not _is_plain_incomplete_branch(
            miss_expression,
            previous_event["completion_variable"],
          ):
            previous_event["miss_condition_text"] = miss_expression
            previous_event["missed_name"] = _missed_screen_name(
              lines,
              i,
              indentation,
            )
        condition_blocks.append((indentation, _screen_condition_variable(line)))
      elif line.startswith("else:"):
        condition_blocks.append((indentation, None))

    if "use game_menu(_(" in line and (" Events" in line or " SCENES" in line):
      current_event_group = line.split('"')[1].replace(" Events", "").capitalize()
      current_event_chapter = None
      continue

    chapter_match = re.match(r'^label\s+"(Chapter\s+\d+)"', line, re.IGNORECASE)
    if current_event_group == "Main" and chapter_match:
      current_event_chapter = chapter_match.group(1).title()
      continue

    if not current_event_group or not line.startswith("textbutton _(\""):
      continue

    name = line.split('"')[1]
    name = name.replace("✓", "")
    name = re.sub(r"\(.*?\)", "", name)
    name = re.sub(r"\{.*?\}", "", name)
    name = name.strip()

    replay_id = None
    for action_line in lines[i + 1:i + 5]:
      replay_match = re.search(r'Replay\("([^"]+)"', action_line)
      if replay_match:
        replay_id = replay_match.group(1)
        break

    if replay_id is None:
      continue

    completion_variable = _choose_completion_variable(
      condition_blocks,
      replay_id,
    )
    logical_key = (current_event_group, name, completion_variable)
    if replay_id in events or logical_key in logical_event_keys:
      continue

    logical_event_keys.add(logical_key)
    events[replay_id] = {
      "id": replay_id,
      "name": name,
      "group": current_event_group,
      "chapter": current_event_chapter,
      "completion_variable": completion_variable,
      "complete": None,
      "missed": False,
      "miss_condition_text": None,
      "missed_name": None,
      "category": None,
      "ready_to_trigger": None,
      "code": None,
      "event_code": None,
      "event_rpath": None,
      "trigger_code": None,
      "trigger_rpath": None,
      "jump_to_file": None,
      "condition_text": None,
      "condition_expression": None,
      "condition_error": None,
      "requirements_satisfied": None,
      "trigger_conditions": [],
      "additional_conditions": [],
      "conditions": [],
    }

    matching_blocks = [
      indentation
      for indentation, variable in condition_blocks
      if variable == completion_variable
    ]
    if matching_blocks:
      condition_indentation = max(matching_blocks)
      last_event_by_condition_indent[condition_indentation] = replay_id
      events[replay_id]["category"] = _screen_event_category(
        lines,
        i,
        condition_indentation,
      )

    if events[replay_id]["category"] is None:
      category_source = " ".join((replay_id, completion_variable)).lower()
      if "invite" in category_source:
        events[replay_id]["category"] = "invite"
      elif "lust" in category_source:
        events[replay_id]["category"] = "lust"

  return events


def load_latest_save(save_folder):
  """Loads the newest readable save, falling back when a save is incomplete."""
  warnings = []
  if not os.path.isdir(save_folder):
    return None, {}, warnings

  save_files = [
    os.path.join(save_folder, name)
    for name in os.listdir(save_folder)
    if name.endswith(".save")
  ]
  save_files.sort(key=os.path.getmtime, reverse=True)

  for save_file in save_files:
    try:
      with zipfile.ZipFile(save_file, "r") as save_zip:
        save_data = parse_save_log(save_zip.read("log"))
      return save_file, save_data, warnings
    except (OSError, KeyError, EOFError, ValueError, zipfile.BadZipFile) as error:
      warnings.append(
        f"Skipped unreadable save {os.path.basename(save_file)}: {error}"
      )

  return None, {}, warnings


def game_structure_signature(script_files):
  """Returns a stable signature that changes when any Ren'Py source changes."""
  signature = []
  for path in script_files:
    stat = os.stat(path)
    signature.append((path, stat.st_mtime_ns, stat.st_size))
  return tuple(signature)


def merge_persistent_values(events, save_folder, save_data, warnings):
  """Adds replay flags stored in Ren'Py's persistent file to save values."""
  persistent_fields = {
    details["completion_variable"].split(".", 1)[1]
    for details in events.values()
    if details["completion_variable"].startswith("persistent.")
  }
  persistent_file = os.path.join(save_folder, "persistent")
  if not persistent_fields or not os.path.exists(persistent_file):
    return
  try:
    with open(persistent_file, "rb") as file:
      decompressor = zlib.decompressobj()
      persistent_pickle = decompressor.decompress(file.read())
    persistent_data = parse_persistent_data(persistent_pickle, persistent_fields)
    save_data.update(persistent_data)
    print(f"Loaded {len(persistent_data)} persistent variables")
  except (OSError, ValueError, zlib.error) as error:
    warning = f"Could not read persistent data: {error}"
    warnings.append(warning)
    print("WARNING: " + warning)


def apply_save_state(events, save_data):
  """Evaluates a cached static event structure against one save file."""
  completion_to_event = {
    event["completion_variable"]: event_name
    for event_name, event in events.items()
  }

  for event in events.values():
    completion_variable = event["completion_variable"]
    event["complete"] = save_data.get(completion_variable) is True
    event["missed"] = False
    event["ready_to_trigger"] = False
    event["requirements_satisfied"] = None
    event["conditions"] = []
    event["miss_conditions"] = []
    event["required_events"] = []
    event.pop("post_events", None)
    event.pop("condition_expression", None)
    event.pop("condition_error", None)
    event.pop("miss_condition_error", None)

  # Evaluate complete Ren'Py conditions, preserving parentheses and OR branches.
  for event_name, event in events.items():
    miss_expression = event.get("miss_condition_text")
    if miss_expression and not event["complete"]:
      missed, miss_conditions, miss_error = evaluate_condition(
        miss_expression,
        save_data,
      )
      event["missed"] = missed is True
      event["miss_conditions"] = miss_conditions
      for condition in miss_conditions:
        required_event = completion_to_event.get(condition["variable"])
        if required_event is None and condition["variable"] in events:
          required_event = condition["variable"]
        condition["event_id"] = required_event
      if miss_error:
        event["miss_condition_error"] = miss_error

    trigger_conditions = list(dict.fromkeys(event["trigger_conditions"]))
    additional_conditions = list(dict.fromkeys(event["additional_conditions"]))
    expression_parts = []
    if trigger_conditions:
      expression_parts.append(
        "(" + ") or (".join(trigger_conditions) + ")"
      )
    expression_parts.extend(
      "(" + condition + ")" for condition in additional_conditions
    )

    if not expression_parts:
      continue

    condition_expression = " and ".join(expression_parts)
    event["condition_expression"] = condition_expression
    if len(trigger_conditions) > 1:
      event["condition_text"] = " OR ".join(trigger_conditions)

    satisfied, conditions, error = evaluate_condition(
      condition_expression,
      save_data,
    )
    event["requirements_satisfied"] = satisfied is True
    event["conditions"] = conditions
    event["condition_error"] = error
    event["ready_to_trigger"] = (
      satisfied is True
      and not event["complete"]
      and not event["missed"]
      and not event.get("chain_sources")
    )

    for condition in conditions:
      required_event = completion_to_event.get(condition["variable"])
      if required_event is None and condition["variable"] in events:
        required_event = condition["variable"]
      condition["event_id"] = required_event
      if required_event is None or required_event == event_name:
        continue
      if required_event not in event["required_events"]:
        event["required_events"].append(required_event)
      post_events = events[required_event].setdefault("post_events", [])
      if event_name not in post_events:
        post_events.append(event_name)


def save_timestamp_text(save_file):
  if save_file is None:
    return "No save found"
  timestamp = os.path.getmtime(save_file)
  return datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')


def load_game_data(game_folder):
  """
  Loads all the game data along with savegame state.

  Args:
      game_folder (_type_): _description_
  
  Returns:
      (dict, dict, list, savegame, time): (Dictionary of all the parsed events, Dictionary of all the save data, character list)
  """
  global last_load_warnings, last_load_stats
  last_load_warnings = []
  last_load_stats = {}

  # Load the most recent save file
  save_folder = os.path.join(game_folder, "game", "saves")
  save_file, save_data, save_warnings = load_latest_save(save_folder)
  last_load_warnings.extend(save_warnings)
  if save_file is not None:
    print(f"Loading most recent readable save file: {save_file}...")
  
  if save_file == None:
    print("No save file found.")

  print(f"Loaded {len(save_data)} saved variables")

  # Load the character names
  characters = []
  newchecker_file = os.path.join(game_folder, "game", "newchecker.rpy")
  if os.path.exists(newchecker_file):
    script = read_text_cached(newchecker_file)

    character_section = script.split("#HAPPY (7 NON-MISSABLE/4 MISSABLE)")[-1].split("#NORIKO NUDES")[0]

    # Extract all character event names
    lines = character_section.split("\n")
    character = None
    for line in lines:
      line = line.strip()
      if line.startswith("#"):
        character = line.split(" ")[0][1:]
        characters.append(character.capitalize())

  print(f"Loaded {len(characters)} characters")
  print(f"Characters: {characters}")

  script_files = discover_script_files(game_folder)
  last_load_stats["script_files"] = len(script_files)
  structure_signature = game_structure_signature(script_files)
  cache_key = os.path.normcase(os.path.abspath(game_folder))
  cached_structure = _GAME_STRUCTURE_CACHE.get(cache_key)
  if cached_structure and cached_structure[0] == structure_signature:
    last_load_stats["cache_hit"] = True
    events = copy.deepcopy(cached_structure[1])
    merge_persistent_values(
      events,
      save_folder,
      save_data,
      last_load_warnings,
    )
    apply_save_state(events, save_data)
    print(f"Reused cached event structure for {len(events)} events")
    return (
      events,
      save_data,
      characters,
      save_file,
      save_timestamp_text(save_file),
    )
  last_load_stats["cache_hit"] = False

  # Parse screens.rpy to load all the events
  screens_file = os.path.join(game_folder, "game", "screens.rpy")
  events = parse_screen_events(read_text_cached(screens_file))
  merge_persistent_values(
    events,
    save_folder,
    save_data,
    last_load_warnings,
  )

  print(f"Loaded {len(events)} named events")
  # Print the number of events by group
  for group, event_set in groupby(sorted(events.values(), key=lambda e: e["group"]), key=lambda e: e["group"]):
    print(f"  {group}: {len(list(event_set))}")


  # Update the events on if they are complete or not
  for event, details in events.items():
    completion_variable = details["completion_variable"]
    if completion_variable in save_data and save_data[completion_variable] == True:
      details["complete"] = True
    else:
      details["complete"] = False
    details["ready_to_trigger"] = False
    details["code"] = "no code found (this usually means it's part of an automatic event chain)"
    details["jump_to_file"] = []
    details["required_events"] = []

  # Parse all script files to requirements to the main and character events
  label_to_jumps = {}
  for script_file in script_files:
    print(f"Processing {script_file}...")
    script = read_text_cached(script_file)
    lines = script.split("\n")

    label = None
    had_jump = True
    for i, line in enumerate(lines):
      # Create a map of jumps to the event label they are in. This is used to
      # unwind automatic event chains to their player-triggered source.
      if line.startswith("label "):
        new_label = line.split(" ")[1].split(":")[0]
        if not had_jump and label is not None:
          label_to_jumps.setdefault(new_label, []).append(label)
          label_to_jumps[new_label] = list(set(label_to_jumps[new_label]))

        label = new_label
        had_jump = False

        if label in events and events[label]["event_code"] is None:
          code_lines = []
          for n in range(0, 20000):
            if i + n >= len(lines):
              break
            if n > 0 and lines[i + n].strip().startswith("label "):
              break
            code_lines.append(lines[i + n])
          events[label]["event_code"] = "...\n" + "\n".join(code_lines) + "\n..."
          events[label]["event_rpath"] = script_file.replace(game_folder, "")

      stripped_line = line.strip()
      if stripped_line.startswith("jump "):
        had_jump = True
        target_label = stripped_line.split(" ")[1].split("#")[0].strip()
        if label is not None:
          label_to_jumps.setdefault(target_label, []).append(label)
          label_to_jumps[target_label] = list(set(label_to_jumps[target_label]))

        event_name = target_label
        if event_name in events:
          if script_file not in events[event_name]["jump_to_file"]:
            events[event_name]["jump_to_file"].append(script_file)

          trigger_code = concise_trigger_code(lines, i)
          events[event_name]["trigger_code"] = trigger_code
          events[event_name]["trigger_rpath"] = script_file.replace(game_folder, "")

          condition_statement, condition_line = find_trigger_condition(lines, i)
          if condition_statement is not None:
            if condition_statement not in events[event_name]["trigger_conditions"]:
              events[event_name]["trigger_conditions"].append(condition_statement)
            events[event_name]["condition_text"] = condition_statement
            events[event_name]["code"] = trigger_code
  
  # Remove label_to_jumps with more than two jumps
  # This is to remove the jump chains that are not actually events
  deletes = []
  for label, jumps in label_to_jumps.items():
    if len(jumps) > 3:
      deletes.append(label)
  for label in deletes:
    del label_to_jumps[label]

  # Identify branch label ids
  label_counts = {}
  for label, jumps in label_to_jumps.items():
    for jump in jumps:
      if jump in label_counts:
        label_counts[jump] += 1
      else:
        label_counts[jump] = 1

  label_branchers = set()
  for label, count in label_counts.items():
    if count > 5:
      label_branchers.add(label)

  def unwind_label(label, depth, target_set):
    # Unwinds the label unil a label in the target set is found.
    # Returns: (label, depth, [path]) or (None, None, [path]) if not found
    if depth > MAX_CHAIN_DEPTH:
      return (None, None, None)
    if label in target_set:
      return (label, depth, [label])
    
    if label in label_to_jumps:
      labels = label_to_jumps[label]
      
      best_label, best_depth, best_path = (None, None, None)

      # Return the least deep label
      for label in labels:
        result = unwind_label(label, depth + 1, target_set)
        if result != (None, None, None):
          if best_label == None or result[1] < best_depth:
            best_label, best_depth, best_path = result
      
      if best_label != None:
        return (best_label, best_depth, [label] + best_path)
    
    return (None, None, None)

  # Parse all script files to find the events that are triggered by other events
  # label_to_jumps = {label -> [jumping labels]}
  # Unwind the jump chains to find the first actual labelled event, and add it as a chain source
  MAX_CHAIN_DEPTH = 20
  for event_name, event in events.items():
    if event_name in label_to_jumps:
      event["triggered_by"] = label_to_jumps[event_name][0]
    
    # Unwind chain events
    chain_source_name = None
    chain_source_depth = None
    chain_source_path = None
    if event_name in label_to_jumps:
      for label in label_to_jumps[event_name]:
        new_chain_source_name, new_chain_source_depth, new_chain_source_path = unwind_label(label, 0, events)

        if new_chain_source_name is not None:
          if chain_source_name is None or new_chain_source_depth < chain_source_depth:
            chain_source_name = new_chain_source_name
            chain_source_depth = new_chain_source_depth
            chain_source_path = new_chain_source_path
      
    # Unwind branch events
    branch_source_name, branch_source_depth, branch_source_path = unwind_label(event_name, 0, label_branchers)

    # Select the shallowest chain or branch. Default to branch if both are the same depth.
    if chain_source_depth is not None and branch_source_depth is not None:
      if chain_source_depth < branch_source_depth:
        events[event_name]["chain_sources"] = chain_source_name
        events[event_name]["chain_sources_depth"] = chain_source_depth
        events[event_name]["chain_sources_path"] = chain_source_path
      else:
        events[event_name]["triggered_by_branch"] = branch_source_name
        events[event_name]["triggered_by_branch_depth"] = branch_source_depth
        events[event_name]["triggered_by_branch_path"] = branch_source_path
    elif chain_source_depth is not None:
      events[event_name]["chain_sources"] = chain_source_name
      events[event_name]["chain_sources_depth"] = chain_source_depth
      events[event_name]["chain_sources_path"] = chain_source_path
    elif branch_source_depth is not None:
      events[event_name]["triggered_by_branch"] = branch_source_name
      events[event_name]["triggered_by_branch_depth"] = branch_source_depth
      events[event_name]["triggered_by_branch_path"] = branch_source_path

  # Parse Phone.rpy getContacts() to get the call and invite over pre-requisites.
  # Add these as requirements to the events.
  invite_pre_reqs = {}
  call_pre_reqs = {}
  phone_file = os.path.join(game_folder, "game", "Phone.rpy")
  if os.path.exists(phone_file):
    phone_script = read_text_cached(phone_file)
    if "contactsList = [" in phone_script:
      region = phone_script.split("contactsList = [")[1].split("]")[0]
      contacts = region.split("Contact(")
      for contact in contacts:
        contact = contact.split("\n")[0]
        tokens = contact.split(",")

        if len(tokens) >= 9:
          id_prefix = tokens[0].replace("\"","").strip()
          id_req_call = tokens[7].strip()
          id_req_invite = tokens[8].replace(")","").strip()

          if id_req_call not in ["True","False"]:
            call_pre_reqs[id_prefix] = id_req_call

          if id_req_invite not in ["True","False"]:
            invite_pre_reqs[id_prefix] = id_req_invite
  
  # Add the phone pre-requisites to the events
  for event_name, event in events.items():
    def get_call_name(id):
      if not(id.startswith("call") and (id.endswith("morning") or id.endswith("afternoon") or id.endswith("night"))):
        return None
      
      # Extract the name
      name = id[4:].replace("morning","").replace("afternoon","").replace("night","")
      return name

    def get_invite_name(id):
      if not(id.endswith("invite") or id[:-1].endswith("invite")):
        return None
      
      # Extract the name
      name = id.replace("invite","")
      while name and name[-1].isdigit():
        name = name[:-1]

      return name
    
    for id in [event_name, event["triggered_by"] if "triggered_by" in event else None]:
      if id is not None:
        # Add call pre-requisites
        name = get_call_name(id)
        
        if name is not None and name in call_pre_reqs:
          events[event_name]["call_pre_req"] = call_pre_reqs[name]
          condition = call_pre_reqs[name]
          if condition not in event["additional_conditions"]:
            event["additional_conditions"].append(condition)
        
        # Add invite pre-requisites
        name = get_invite_name(id)
        if name is not None and name in invite_pre_reqs:
          events[event_name]["invite_pre_req"] = invite_pre_reqs[name]
          condition = invite_pre_reqs[name]
          if condition not in event["additional_conditions"]:
            event["additional_conditions"].append(condition)


  # Add custom conditions. Used to add conditions that are not parsed in the game script.
  # These are mostly introductions of new characters.
  custom_conditions = {
    # "event_name": ["condition1", "condition2"],
    "iofirsthall": ["day247"],
    "utafirsthall": ["day247"],
    "yasufirsthall": ["day304"],
    "toukafirsthall": ["day304"],
    "toukastreets1": ["day304"],
    "ramen1": ["day154"],
    "tsuneyofirsthall": ["day154"],
    "otohafirsthall": ["day288"],
    "mollycafe1": ["day154"],
    "mollyfirsthall": ["day154"],
    "kirindate1": ["soccer20"],
    "kirinfirsthall": ["day271"],
    "nodokafirsthall": ["day288"],
    "norikofirsthall": ["day271"],
    "osakodojo1": ["osakodate1"],
    "harukafirstlust": ["harukadate1"],
    "harukalust10": ["harukadate1"],
  }
  for event_name, conditions in custom_conditions.items():
    if event_name in events:
      for condition in conditions:
        if condition not in events[event_name]["additional_conditions"]:
          events[event_name]["additional_conditions"].append(condition)

  _GAME_STRUCTURE_CACHE[cache_key] = (
    structure_signature,
    copy.deepcopy(events),
  )
  apply_save_state(events, save_data)
  save_file_timestamp = save_timestamp_text(save_file)

  return (events, save_data, characters, save_file, save_file_timestamp)
