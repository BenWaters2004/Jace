import re
from urllib.parse import urlparse


ALL_TOOL_NAMES = {
    "calculator",
    "current_datetime",
    "search_memory",
    "search_conversations",
    "rename_current_conversation",
    "create_memory",
    "deactivate_memory",
    "web_search",
    "read_web_page",
    "browser_read_page",
    "list_computer_workspaces",
    "list_workspace_files",
    "read_workspace_file",
    "search_workspace_files",
    "workspace_file_info",
    "create_workspace_directory",
    "write_workspace_file",
    "replace_workspace_text",
    "move_workspace_path",
    "delete_workspace_file",
    "run_workspace_command",
    "computer_locations",
    "list_host_directory",
    "read_host_file",
    "host_file_info",
    "search_host_files",
    "write_host_file",
    "replace_host_text",
    "move_host_path",
    "delete_host_path",
    "run_shell_command",
    "inspect_host_media",
    "workspace_overview",
    "workspace_tree",
    "workspace_recent_files",
    "find_workspace_paths",
    "preview_workspace_edit",
    "inspect_attachment",
    "inspect_workspace_media",
    "capture_screen",
    "list_automations",
    "create_automation",
    "set_automation_enabled",
    "run_automation_now",
    "start_control_session",
    "control_status",
    "list_control_windows",
    "focus_control_window",
    "capture_control_screen",
    "move_control_pointer",
    "click_control",
    "scroll_control",
    "type_control_text",
    "press_control_keys",
    "stop_control_session",
    "calendar_list_events",
    "calendar_next_event",
    "calendar_free_busy",
    "calendar_check_conflicts",
    "calendar_find_open_slots",
    "calendar_find_event",
    "list_execution_devices",
    "inspect_device_command",
    "run_device_command",
    "get_device_process",
    "read_device_process_output",
    "stop_device_process",
    "open_device_terminal",
    "read_device_terminal_output",
    "send_device_terminal_input",
    "resize_device_terminal",
    "close_device_terminal",
}


def _contains_url(text: str) -> bool:
    for candidate in re.findall(r"https?://[^\s<>()]+", text, flags=re.IGNORECASE):
        parsed = urlparse(candidate.rstrip(".,;:!?)]}"))
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return True
    return False


def _looks_like_arithmetic(text: str) -> bool:
    stripped = text.strip()
    if re.fullmatch(r"[\d\s().,+\-*/%^]+", stripped) and re.search(r"\d", stripped):
        return True
    return bool(
        re.search(
            r"\b(?:calculate|calculator|work out|what is|what's)\b.{0,40}\d+\s*(?:\+|-|\*|/|%|\^)",
            text,
            flags=re.IGNORECASE,
        )
    )


def route_tool_names(message: str) -> set[str]:
    """Return only tool schemas that are plausibly useful for this request."""
    text = " ".join(message.strip().split())
    lowered = text.lower()
    selected: set[str] = set()

    if not text:
        return selected

    if re.search(r"\b(?:use|show|list) all tools\b", lowered):
        return set(ALL_TOOL_NAMES)

    if _looks_like_arithmetic(text):
        selected.add("calculator")

    if re.search(
        r"\b(?:current time|what time|time is it|current date|today'?s date|what date|day is it|date and time)\b",
        lowered,
    ):
        selected.add("current_datetime")

    if re.search(
        r"\b(?:remember|recall|memory|what do you know about me|what do you remember|my saved memory|saved memories)\b",
        lowered,
    ):
        selected.add("search_memory")

    if re.search(
        r"\b(?:past conversations?|previous conversations?|last conversation|chat history|conversation history|search (?:my )?(?:past |previous )?(?:chats|conversations)|what did (?:i|we) (?:say|discuss|talk about)|what were we (?:discussing|talking about))\b",
        lowered,
    ):
        selected.add("search_conversations")

    if re.search(r"\b(?:rename|retitle)\b.{0,30}\b(?:chat|conversation|this)\b", lowered):
        selected.add("rename_current_conversation")

    if re.search(r"\b(?:create|add|save|store)\b.{0,25}\bmemory\b", lowered):
        selected.add("create_memory")
    if re.search(r"\b(?:deactivate|disable|remove)\b.{0,25}\bmemory\b", lowered):
        selected.update({"search_memory", "deactivate_memory"})

    has_url = _contains_url(text)
    if has_url:
        selected.update({"read_web_page", "browser_read_page"})

    if re.search(
        r"\b(?:search (?:the )?web|search online|look online|look up(?: online)?|google|latest|recent news|news about|find online|internet search|current information|current info)\b",
        lowered,
    ):
        selected.update({"web_search", "read_web_page", "browser_read_page"})

    if re.search(
        r"\b(?:weather|forecast|stock price|share price|price of|current president|current prime minister|current ceo|latest version|latest release|today'?s news|recent developments)\b",
        lowered,
    ):
        selected.update({"web_search", "read_web_page", "browser_read_page"})

    if re.search(
        r"\b(?:research|find sources|find articles|find documentation|latest documentation|find information about)\b",
        lowered,
    ):
        selected.update({"web_search", "read_web_page", "browser_read_page"})

    computer_hint = re.search(
        r"\b(?:my (?:file|files|folder|folders|directory|directories|project|repo|repository|codebase)|"
        r"local (?:file|files|folder|folders|project|repo|repository)|workspace|working tree|source file|code file)\b",
        lowered,
    )

    if computer_hint or re.search(
        r"\b(?:list|show|find|search|read|open|inspect)\b.{0,30}\b(?:files?|folders?|directories|repo|repository|codebase)\b",
        lowered,
    ):
        selected.add("list_computer_workspaces")

    if re.search(r"\b(?:list|show|browse|what(?:'s| is) in)\b.{0,35}\b(?:files?|folders?|directories|workspace|repo|repository)\b", lowered):
        selected.update({"list_computer_workspaces", "list_workspace_files"})

    if re.search(r"\b(?:read|open|inspect|show|view|look at)\b.{0,40}\b(?:file|source|code|readme|config|configuration)\b", lowered):
        selected.update({"list_computer_workspaces", "read_workspace_file", "workspace_file_info"})

    if re.search(r"\b(?:find|search|locate|grep)\b.{0,35}\b(?:file|files|text|code|project|repo|repository|workspace)\b", lowered):
        selected.update({"list_computer_workspaces", "search_workspace_files", "read_workspace_file"})

    if re.search(r"\b(?:edit|modify|change|update|fix|refactor|replace|write|create)\b.{0,45}\b(?:file|code|source|component|module|class|function|config|configuration)\b", lowered):
        selected.update({
            "list_computer_workspaces",
            "search_workspace_files",
            "read_workspace_file",
            "workspace_file_info",
            "write_workspace_file",
            "replace_workspace_text",
        })

    if re.search(r"\b(?:create|make|add)\b.{0,30}\b(?:folder|directory)\b", lowered):
        selected.update({"list_computer_workspaces", "create_workspace_directory"})

    if re.search(r"\b(?:rename|move)\b.{0,30}\b(?:file|folder|directory|path)\b", lowered):
        selected.update({"list_computer_workspaces", "workspace_file_info", "move_workspace_path"})

    if re.search(r"\b(?:delete|remove)\b.{0,30}\b(?:file)\b", lowered):
        selected.update({"list_computer_workspaces", "workspace_file_info", "delete_workspace_file"})

    if re.search(r"\b(?:run|execute|build|test|tests|lint|format|git status|check the project)\b", lowered) and (
        computer_hint or re.search(r"\b(?:project|repo|repository|workspace|code|build|tests?|lint|git)\b", lowered)
    ):
        selected.update({"list_computer_workspaces", "run_workspace_command"})
    # JACE_STEP4B1_FILESYSTEM_INTELLIGENCE_ROUTING
    filesystem_overview = bool(
        re.search(
            r"\b(?:understand|analyse|analyze|inspect|review|profile|summarise|summarize)\b"
            r".{0,50}\b(?:project|repo|repository|codebase|workspace)\b"
            r"|\b(?:project|repo|repository|codebase|workspace)\b.{0,35}"
            r"\b(?:overview|summary|structure|stack|languages|frameworks)\b",
            lowered,
        )
    )

    filesystem_tree_request = bool(
        re.search(
            r"\b(?:show|list|map|inspect|view)\b.{0,35}\b"
            r"(?:tree|structure|folder structure|directory structure)\b"
            r"|\b(?:project|repo|repository|codebase|workspace)\s+tree\b",
            lowered,
        )
    )

    filesystem_recent_request = bool(
        re.search(
            r"\b(?:recent|recently|latest)\b.{0,30}\b"
            r"(?:files?|changes?|modified|edited)\b"
            r"|\b(?:what|which)\b.{0,25}\bfiles?\b.{0,25}"
            r"\b(?:changed|modified|edited)\b",
            lowered,
        )
    )

    filesystem_find_paths = bool(
        re.search(
            r"\b(?:find|locate|show|list)\b.{0,40}\b"
            r"(?:files?|paths?)\b.{0,50}\b"
            r"(?:named|ending in|extension|language|typescript|javascript|"
            r"python|php|react|tsx|jsx|blade|controller|component)\b"
            r"|\b(?:all|which)\b.{0,20}\b"
            r"(?:typescript|javascript|python|php|tsx|jsx|blade)\b.{0,20}\bfiles?\b",
            lowered,
        )
    )

    filesystem_preview = bool(
        re.search(
            r"\b(?:preview|show)\b.{0,30}\b(?:diff|edit|change|patch)\b"
            r"|\b(?:what would|what will)\b.{0,30}\b(?:change|edit)\b"
            r"|\bbefore (?:writing|editing|changing)\b",
            lowered,
        )
    )

    if filesystem_overview:
        # JACE_STEP4B1_V3_DIRECT_WORKSPACE_ROUTING
        selected.discard("list_computer_workspaces")
        selected.add("workspace_overview")

    if filesystem_tree_request:
        # JACE_STEP4B1_V3_DIRECT_WORKSPACE_ROUTING
        selected.discard("list_computer_workspaces")
        selected.add("workspace_tree")

    if filesystem_recent_request:
        # JACE_STEP4B1_V3_DIRECT_WORKSPACE_ROUTING
        selected.discard("list_computer_workspaces")
        selected.add("workspace_recent_files")

    if filesystem_find_paths:
        # This is filename/path discovery rather than text-content search.
        selected.discard("search_workspace_files")
        selected.discard("read_workspace_file")
        # JACE_STEP4B1_V3_DIRECT_WORKSPACE_ROUTING
        selected.discard("list_computer_workspaces")
        selected.add("find_workspace_paths")

    if filesystem_preview:
        # A preview request must never accidentally route an actual write tool.
        selected.discard("write_workspace_file")
        selected.discard("replace_workspace_text")
        # JACE_STEP4B1_V3_DIRECT_WORKSPACE_ROUTING
        selected.discard("list_computer_workspaces")
        selected.add("preview_workspace_edit")


    # JACE_STEP4B2_FULL_HOST_ACCESS_ROUTING
    explicit_host_path = bool(
        re.search(
            r"(?:[A-Za-z]:\\|[A-Za-z]:/|\\\\[^\\\s]+\\|"
            r"\b(?:desktop|documents|downloads|pictures|videos|music)\b)",
            text,
            flags=re.IGNORECASE,
        )
    )

    shell_request = bool(
        re.search(
            r"\b(?:powershell|pwsh|cmd(?:\.exe)?|command prompt|bash|wsl)\b"
            r"|\b(?:run|execute)\b.{0,50}\b(?:command|script|shell)\b",
            lowered,
        )
    )

    host_read_request = bool(
        re.search(
            r"\b(?:read|open|inspect|show|view)\b.{0,45}\b(?:file|text|contents?)\b",
            lowered,
        )
    )

    # JACE_STEP4B2_V2_HOST_LIST_ROUTING_FIX
    host_list_request = bool(
        re.search(
            r"\b(?:list|show|browse|inspect)\b.{0,50}\b"
            r"(?:folder|directory|files|contents?)\b"
            r"|\bwhat(?:'s| is)\s+in\b"
            r"|\bshow me what(?:'s| is)\s+in\b",
            lowered,
        )
    )

    host_search_request = bool(
        re.search(
            r"\b(?:find|search|locate)\b.{0,50}\b(?:file|files|text|contents?)\b",
            lowered,
        )
    )

    host_info_request = bool(
        re.search(
            r"\b(?:file info|file information|metadata|sha256|hash)\b",
            lowered,
        )
    )

    host_write_request = bool(
        re.search(
            r"\b(?:write|create|save)\b.{0,50}\b(?:file|text file)\b",
            lowered,
        )
    )

    host_edit_request = bool(
        re.search(
            r"\b(?:edit|modify|replace|change|update)\b.{0,50}\b(?:file|text)\b",
            lowered,
        )
    )

    host_move_request = bool(
        re.search(
            r"\b(?:move|rename)\b.{0,60}\b(?:file|folder|directory|path)\b",
            lowered,
        )
    )

    host_delete_request = bool(
        re.search(
            r"\b(?:delete|remove)\b.{0,60}\b(?:file|folder|directory|path)\b",
            lowered,
        )
    )


    # JACE_STEP4B2_V3_HOST_MEDIA_ROUTING
    host_media_request = bool(
        explicit_host_path
        and re.search(
            r"\.(?:docx|pdf|png|jpe?g|webp|gif|bmp|wav|mp3|m4a|"
            r"flac|ogg|oga|webm|aac|wma)\b",
            lowered,
        )
        and re.search(
            r"\b(?:read|open|inspect|show|view|look at|describe|analyse|analyze|"
            r"summarise|summarize|transcribe)\b",
            lowered,
        )
    )

    host_file_from_directory = bool(
        explicit_host_path
        and re.search(
            r"\bread\b.{0,30}\b(?:text|document|docx|pdf)?\s*file\b"
            r".{0,20}\bfrom\b",
            lowered,
        )
        and not re.search(
            r"\.[A-Za-z0-9]{1,8}(?:[.!?;,]*)?\s*$",
            text,
        )
    )

    if shell_request:
        selected.add("run_shell_command")

    if explicit_host_path:
        for name in (
            "list_computer_workspaces",
            "list_workspace_files",
            "read_workspace_file",
            "search_workspace_files",
            "workspace_file_info",
            "write_workspace_file",
            "replace_workspace_text",
            "move_workspace_path",
            "delete_workspace_file",
        ):
            selected.discard(name)

        if host_read_request:
            selected.add("read_host_file")
        if host_list_request:
            selected.add("list_host_directory")
        if host_search_request:
            selected.add("search_host_files")
        if host_info_request:
            selected.add("host_file_info")
        if host_write_request:
            selected.add("write_host_file")
        if host_edit_request:
            selected.add("replace_host_text")
        if host_move_request:
            selected.add("move_host_path")
        if host_delete_request:
            selected.add("delete_host_path")

    if host_file_from_directory:
        selected.discard("read_host_file")
        selected.add("list_host_directory")

    if host_media_request:
        selected.discard("read_host_file")
        selected.discard("host_file_info")
        selected.add("inspect_host_media")

    if re.search(
        r"\b(?:what drives|which drives|computer locations|"
        r"where are my (?:downloads|documents|desktop)|"
        r"show my drives)\b",
        lowered,
    ):
        selected.add("computer_locations")

    # Phase 7 multimodal. User-attached media is injected directly in the
    # current turn. These schemas are for later references, workspace media,
    # and permissioned live screen capture.
    if re.search(
        r"\b(?:attachment|attached|image|photo|picture|screenshot|pdf|document|audio|voice note|recording)\b",
        lowered,
    ):
        selected.add("inspect_attachment")

    if re.search(
        r"\b(?:look at|inspect|analyse|analyze|read|open|view|transcribe)\b.{0,45}"
        r"\b(?:image|photo|picture|pdf|document|audio|recording|voice note)\b",
        lowered,
    ) and computer_hint:
        selected.update({"list_computer_workspaces", "inspect_workspace_media"})

    if re.search(
        r"\b(?:look at|inspect|see|capture|take (?:a )?screenshot of|what(?:'s| is) on)\b.{0,35}"
        r"\b(?:my |the |current )?(?:screen|display|monitor|desktop)\b",
        lowered,
    ):
        selected.add("capture_screen")

    # Phase 8 automation. Include current_datetime when creating a schedule so
    # the model can resolve relative wording such as tomorrow or in two hours.
    if re.search(
        # JACE_STEP4C5B_AUTOMATION_SCHEDULE_DISAMBIGUATION
        # Bare "schedule" is ambiguous with Calendar creation. Automation intent is
        # already covered by remind me / automation / recurring / tomorrow-at / every-X forms.
        r"\b(?:remind me|automation|automations|recurring task|watcher|every (?:day|weekday|week|hour|morning|evening)|"
        r"tomorrow at|in \d+ (?:minutes?|hours?|days?)|notify me when|tell me when|monitor|check every)\b",
        lowered,
    ):
        selected.update({"list_automations", "create_automation", "current_datetime"})

    if re.search(r"\b(?:list|show|what are|which)\b.{0,25}\bautomations?\b", lowered):
        selected.add("list_automations")

    if re.search(r"\b(?:enable|disable|pause|resume)\b.{0,35}\b(?:automation|task|watcher)\b", lowered):
        selected.update({"list_automations", "set_automation_enabled"})

    if re.search(r"\b(?:run|execute|start)\b.{0,35}\b(?:automation|scheduled task|watcher)\b", lowered):
        selected.update({"list_automations", "run_automation_now"})

    # JACE_STEP4C4F_CALENDAR_INTELLIGENCE_ROUTING
    calendar_intent = bool(
        re.search(
            r"\b(?:calendar|calendars|meeting|meetings|appointment|appointments|"
            r"agenda|free time|free slot|available|availability|busy|conflict|"
            r"clash|gap|open slot|time slot)\b",
            lowered,
        )
    )
    implicit_calendar_question = bool(
        re.search(
            r"\b(?:"
            r"what (?:do i have|have i got|am i doing) (?:today|tomorrow|on |this |next )|"
            r"what have i got (?:today|tomorrow|on |this |next )|"
            r"what(?:'s| is) (?:on|in) my (?:day|week)|"
            r"when am i free|when (?:do i|can i) have time|"
            r"find (?:me )?(?:an? )?(?:free|open) (?:time|slot|gap)|"
            r"do i have anything (?:today|tomorrow|on )|"
            r"am i free|am i busy"
            r")\b",
            lowered,
        )
    )

    if calendar_intent or implicit_calendar_question:
        selected.update({
            "calendar_list_events",
            "calendar_next_event",
            "calendar_free_busy",
            "calendar_check_conflicts",
            "calendar_find_open_slots",
        })

        if re.search(
            r"\b(?:today|tomorrow|tonight|this (?:week|weekend|morning|afternoon|evening)|"
            r"next (?:week|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
            r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
            r"in \d+ (?:minutes?|hours?|days?))\b",
            lowered,
        ):
            selected.add("current_datetime")

    # JACE_STEP4C4F_CALENDAR_DATE_ROUTING_FIX
    # Calendar date questions must expose both Calendar Intelligence and the
    # clock. This prevents relative/incomplete phrases from being converted to
    # an invented ISO range by the model.
    calendar_request = bool(
        re.search(
            r"\b(?:calendar|calendars|agenda|meeting|meetings|appointment|appointments|"
            r"free time|free slot|available|availability|busy|conflict|clash|"
            r"open slot|time slot)\b",
            lowered,
        )
        or re.search(
            r"\b(?:what (?:do i have|have i got|am i doing)|what have i got|"
            r"do i have anything|am i free|am i busy|when am i free|"
            r"find (?:me )?(?:an? )?(?:free|open) (?:time|slot|gap))\b",
            lowered,
        )
    )

    calendar_date_phrase = bool(
        re.search(
            r"\b(?:today|yesterday|tomorrow|day before yesterday|day after tomorrow|"
            r"this week|last week|next week|this weekend|next weekend|"
            r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            lowered,
        )
        or re.search(
            r"\b(?:the\s+)?\d{1,2}(?:st|nd|rd|th)\b",
            lowered,
        )
        or re.search(
            r"\b\d{4}-\d{2}-\d{2}\b",
            lowered,
        )
        or re.search(
            r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
            lowered,
        )
    )

    if calendar_request:
        selected.update({
            "calendar_list_events",
            "calendar_next_event",
            "calendar_free_busy",
            "calendar_check_conflicts",
            "calendar_find_open_slots",
        })

        if calendar_date_phrase:
            selected.add("current_datetime")

    # JACE_STEP4C5A_CALENDAR_MODIFY_ROUTING
    calendar_modify_followup = bool(
        re.search(
            r"\b(?:move|reschedule|update|change|edit|cancel|delete|remove)\b",
            lowered,
        )
        and (
            re.search(
                r"\b(?:calendar|event|meeting|appointment)\b",
                lowered,
            )
            or re.search(
                r"\b(?:to|from|at)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b",
                lowered,
            )
            or re.search(
                r"[\"“”‘’'][^\"“”‘’']+[\"“”‘’']",
                text,
            )
        )
    )

    if calendar_modify_followup:
        selected.add("calendar_find_event")

        for name in (
            "calendar_list_events",
            "calendar_next_event",
            "calendar_free_busy",
            "calendar_check_conflicts",
            "calendar_find_open_slots",
        ):
            if name in ALL_TOOL_NAMES:
                selected.add(name)

        if re.search(
            r"\b(?:today|yesterday|tomorrow|monday|tuesday|wednesday|"
            r"thursday|friday|saturday|sunday|this week|next week)\b",
            lowered,
        ):
            selected.add("current_datetime")

    # JACE_STEP4C5B_SCHEDULING_ROUTING
    calendar_scheduling_change = bool(
        re.search(
            r"\b(?:invite|add|remove)\b.{0,120}\b(?:attendee|attendees|guest|guests|invitee|invitees)\b"
    r"|\b(?:invite|add|remove)\b.{0,120}\b[^@\s]+@[^@\s]+\b"
    r"|\b(?:invite|add|remove)\b.{0,120}[\"“”‘’'][^\"“”‘’']+[\"“”‘’']"
            r"|\b(?:make|set|change|update)\b.{0,120}\b(?:recurring|recurrence|repeat|repeating)\b"
            r"|\b(?:add|set|change|remove)\b.{0,120}\b(?:reminder|reminders)\b"
            r"|\b(?:add|create|remove)\b.{0,120}\b(?:google meet|meet link|teams|teams link|online meeting)\b"
            r"|\b(?:change|update|delete|cancel)\b.{0,120}\b(?:series|occurrence)\b",
            lowered,
        )
    )

    if calendar_scheduling_change:
        selected.add("calendar_find_event")

        for name in (
            "calendar_list_events",
            "calendar_next_event",
            "calendar_free_busy",
            "calendar_check_conflicts",
            "calendar_find_open_slots",
        ):
            if name in ALL_TOOL_NAMES:
                selected.add(name)

        if re.search(
            r"\b(?:today|yesterday|tomorrow|monday|tuesday|wednesday|"
            r"thursday|friday|saturday|sunday|this week|next week)\b",
            lowered,
        ):
            selected.add("current_datetime")

    # Phase 9 interactive GUI control. Selecting the family lets the model
    # observe first and then act within an approved short-lived session.
    if re.search(
        r"\b(?:click|type|press|scroll|move (?:the )?mouse|mouse|keyboard|focus (?:the )?window|"
        r"open (?:it|the app|the window)|use (?:my |the )?(?:browser|desktop|computer)|"
        r"control (?:my |the )?(?:screen|desktop|computer|browser|app)|interact with|fill (?:in|out)|"
        r"operate (?:the |my )?(?:browser|app|application|computer)|do it on my screen)\b",
        lowered,
    ):
        selected.update({
            "start_control_session",
            "control_status",
            "list_control_windows",
            "focus_control_window",
            "capture_control_screen",
            "move_control_pointer",
            "click_control",
            "scroll_control",
            "type_control_text",
            "press_control_keys",
            "stop_control_session",
        })

    if re.search(r"\b(?:stop|cancel|abort|emergency stop)\b.{0,25}\b(?:control|mouse|computer|desktop|browser)\b", lowered):
        selected.update({"control_status", "stop_control_session"})

    # JACE_4B3C_EXECUTION_ROUTING
    execution_shell_intent = bool(
        re.search(
            r"\b(?:powershell|cmd(?:\.exe)?|command prompt|bash|wsl|"
            r"terminal|shell|device agent|remote command)\b",
            lowered,
        )
    )
    execution_command_intent = bool(
        re.search(
            r"\b(?:run|execute|launch|start|invoke)\b.{0,40}"
            r"\b(?:command|script|powershell|cmd|bash|wsl|shell|terminal)\b",
            lowered,
        )
        or re.search(
            r"\b(?:powershell|cmd|bash|wsl)\s+(?:command|script)\b",
            lowered,
        )
    )

    if execution_shell_intent or execution_command_intent:
        selected.add("list_execution_devices")

    if execution_command_intent:
        selected.update(
            {
                "inspect_device_command",
                "run_device_command",
                "get_device_process",
                "read_device_process_output",
            }
        )

    if re.search(
        r"\b(?:process|job)\b.{0,35}"
        r"\b(?:status|output|stdout|stderr|stop|terminate|kill|cancel)\b"
        r"|\b(?:stop|terminate|kill|cancel)\b.{0,35}\b(?:process|job)\b",
        lowered,
    ):
        selected.update(
            {
                "get_device_process",
                "read_device_process_output",
                "stop_device_process",
            }
        )

    if re.search(
        r"\b(?:interactive terminal|terminal session|persistent shell|"
        r"open (?:a )?(?:powershell|cmd|bash|wsl) terminal|"
        r"send .* to (?:the )?terminal|terminal output|terminal scrollback|"
        r"resize (?:the )?terminal|close (?:the )?terminal)\b",
        lowered,
    ):
        selected.update(
            {
                "list_execution_devices",
                "open_device_terminal",
                "read_device_terminal_output",
                "send_device_terminal_input",
                "resize_device_terminal",
                "close_device_terminal",
            }
        )

    return selected
