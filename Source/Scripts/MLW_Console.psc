Scriptname MLW_Console Hidden
{Console: the third hotkey (MCM: Console on, off by default, and a Console hotkey, no key by default). N tells the NPCs
something happened, G gives them an absolute command; this one makes something real in the game ("give me 2000
gold", "make it rain", "teleport me to Whiterun").
During a Mantella conversation it opens the text box Absolute Command uses. The wish is written to
SKSE/Plugins/StorageUtilData/MantellaLivingWorld/console.json and Mantella is asked for an NPC turn (MLW_Command.AskForTurn).
On that turn only, the Hub's side in Mantella offers the model the Console action (mantella_mlwh_console): a few
console commands it writes for the wish and one line saying what they make true. MLW_Channel receives the action and
calls Run: nothing runs before the player picks Run in a box that lists every command. Then the HUD shows what ran
(MLW_Notify) and the NPCs are told the result as a fact, from the summary, never the raw commands. Cancel tells them
nothing: the wish was never part of the story.
Needs ConsoleUtilSSE (NG). Without it the key does nothing but one notice per save. The last runs are kept per save
(StorageUtil MLW_ConsoleLog) for the troubleshooting report, and sent to Mantella's side for its own log.}

string Function HubPlugin() global
	Return "Mantella Living World - Integration Hub.esp"
EndFunction

string Function FilePath() global
	Return "MantellaLivingWorld/console.json"
EndFunction

int Function MaxCommands() global
	Return 5
EndFunction

; Longer commands are left out, never cut: a cut command is another command.
int Function MaxLength() global
	Return 200
EndFunction

; Rows kept in the file and lines in the per-save log.
int Function MaxKept() global
	Return 10
EndFunction

bool Function IsOn() global
	GlobalVariable on = Game.GetFormFromFile(0x000810, HubPlugin()) as GlobalVariable  ; MLW_ConsoleOn
	Return on && on.GetValueInt() == 1
EndFunction

; ConsoleUtil's version, 0 when it is missing. The SKSE plugin first; its script answers too when the plugin name differs.
int Function ToolVersion() global
	int version = SKSE.GetPluginVersion("ConsoleUtilSSE")
	If version > 0
		Return version
	EndIf
	If version == 0
		Return 1
	EndIf
	Return ConsoleUtil.GetVersion()
EndFunction

; The hotkey (MLW_Setup).
Function Give() global
	If !IsOn()
		Debug.Notification("Console is off. Turn it on in the Living World MCM.")
		Return
	EndIf
	int tool = ToolVersion()
	If tool <= 0
		If StorageUtil.GetIntValue(None, "MLW_ConsoleNoTool", 0) == 0
			StorageUtil.SetIntValue(None, "MLW_ConsoleNoTool", 1)
			Debug.Notification("Console needs ConsoleUtilSSE NG.")
		EndIf
		Return
	EndIf
	MantellaConversation talk = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	MLW_Channel channel = Game.GetFormFromFile(0x000823, HubPlugin()) as MLW_Channel
	If !talk || !channel || !talk.IsRunning()
		Debug.Notification("Console: start a Mantella conversation first.")
		Return
	EndIf
	Actor player = Game.GetPlayer()
	string refs = ""
	string names = ""
	int i = 0
	While i < talk.CountActorsInConversation()
		Actor npc = talk.GetActorInConversationByIndex(i)
		If npc && npc != player
			If refs != ""
				refs += ","
				names += "|"
			EndIf
			refs += channel.Hex(npc.GetFormID())
			names += npc.GetDisplayName()
		EndIf
		i += 1
	EndWhile
	UIExtensions.InitMenu("UITextEntryMenu")
	UIExtensions.OpenMenu("UITextEntryMenu")
	string text = UIExtensions.GetMenuResultString("UITextEntryMenu")
	If !MLW_Command.HasText(text) || !talk.IsRunning()
		Return
	EndIf
	float now = Utility.GetCurrentGameTime()
	string path = FilePath()
	JsonUtil.StringListAdd(path, "key", (now as string) + "-" + Utility.RandomInt(0, 999999))
	JsonUtil.StringListAdd(path, "text", text)
	JsonUtil.StringListAdd(path, "refs", refs)
	JsonUtil.StringListAdd(path, "names", names)
	JsonUtil.StringListAdd(path, "time", now as string)
	JsonUtil.StringListAdd(path, "player", player.GetDisplayName())
	JsonUtil.StringListAdd(path, "tool", tool as string)
	While JsonUtil.StringListCount(path, "key") > MaxKept()
		JsonUtil.StringListRemoveAt(path, "key", 0)
		JsonUtil.StringListRemoveAt(path, "text", 0)
		JsonUtil.StringListRemoveAt(path, "refs", 0)
		JsonUtil.StringListRemoveAt(path, "names", 0)
		JsonUtil.StringListRemoveAt(path, "time", 0)
		JsonUtil.StringListRemoveAt(path, "player", 0)
		JsonUtil.StringListRemoveAt(path, "tool", 0)
	EndWhile
	JsonUtil.Save(path)
	Debug.Notification("Console: " + Short(text, 60))
	MLW_Hub hub = Game.GetFormFromFile(0x000820, HubPlugin()) as MLW_Hub
	If hub
		hub.Log("hub", "console wish: " + text)
	EndIf
	MLW_Command.AskForTurn(talk, channel, player.GetDisplayName() + " pauses for a moment.")
EndFunction

; The Console action (MLW_Channel): asCommands as the model wrote them, asSummary what they make true. Cleaned, shown
; in a Run / Cancel box, and only run on Run.
Function Run(string[] asCommands, string asSummary) global
	string summary = Short(OneLine(asSummary), MaxLength())
	If !IsOn() || ToolVersion() <= 0
		MLW_Notify.Hud("Console: nothing was run (Console is off or ConsoleUtil is missing).")
		Return
	EndIf
	string[] commands = new string[5]
	int count = 0
	int dropped = 0
	int i = 0
	While i < asCommands.Length && count < MaxCommands()
		string command = OneLine(asCommands[i])
		If StringUtil.GetLength(command) > MaxLength()
			dropped += 1
		ElseIf command != ""
			commands[count] = command
			count += 1
		EndIf
		i += 1
	EndWhile
	If count == 0
		string why = summary
		If why == ""
			why = "no command was written for it"
		EndIf
		MLW_Notify.Hud("Console: nothing to run. " + why)
		Remember("nothing to run | " + why)
		Return
	EndIf
	string listing = ""
	i = 0
	While i < count
		listing += "\n" + (i + 1) + ". " + commands[i]
		i += 1
	EndWhile
	string note = ""
	If dropped > 0
		note = "\n(" + dropped + " over-long command(s) left out.)"
	EndIf
	string question = "Living World Console: run these console commands in your game?\n\n" + summary + "\n" + listing + note
	If SkyMessage.Show(question, "Run", "Cancel") != "Run"
		MLW_Notify.Hud("Console: cancelled, nothing was run.")
		Remember("cancelled | " + Joined(commands, count) + " | " + summary)
		Return
	EndIf
	ConsoleUtil.SetSelectedReference(None)  ; every command runs with nothing selected unless it says whom
	int failed = 0
	string failures = ""
	i = 0
	While i < count
		ConsoleUtil.PrintMessage("[MLW]")  ; a marker line, so a failure line repeated from the last command is not read as success
		string before = ConsoleUtil.ReadMessage()
		ConsoleUtil.ExecuteCommand(commands[i])
		string after = ConsoleUtil.ReadMessage()
		If after != before && LooksFailed(after)
			failed += 1
			failures += " [" + commands[i] + ": " + Short(after, 80) + "]"
		EndIf
		i += 1
	EndWhile
	If failed == 0
		MLW_Notify.Result("Console ran " + count + " command(s): " + Short(summary, 80), "(Now true in the game: " + summary + ")")
		Remember("ran | " + Joined(commands, count) + " | " + summary)
	ElseIf failed < count
		MLW_Notify.Result("Console: " + failed + " of " + count + " commands failed (see the console).", "(Only partly true in the game, some of it did not work: " + summary + ")")
		Remember("partly ran | " + Joined(commands, count) + " | " + summary + " | failed:" + failures)
	Else
		MLW_Notify.Hud("Console: the commands failed (see the console). Nothing changed.")
		Remember("failed | " + Joined(commands, count) + " | failed:" + failures)
	EndIf
EndFunction

; A console line that says the command did not work.
bool Function LooksFailed(string asLine) global
	Return StringUtil.Find(asLine, "not found") >= 0 || StringUtil.Find(asLine, "Missing parameter") >= 0 || StringUtil.Find(asLine, "not saved") >= 0 || StringUtil.Find(asLine, "Invalid") >= 0 || StringUtil.Find(asLine, "error") >= 0
EndFunction

; The per-save log (the report) and Mantella's side's log (console.json done_key / done_text).
Function Remember(string asLine) global
	float now = Utility.GetCurrentGameTime()
	string line = "[" + now + "] " + asLine
	StorageUtil.StringListAdd(None, "MLW_ConsoleLog", line)
	While StorageUtil.StringListCount(None, "MLW_ConsoleLog") > MaxKept()
		StorageUtil.StringListRemoveAt(None, "MLW_ConsoleLog", 0)
	EndWhile
	string path = FilePath()
	JsonUtil.StringListAdd(path, "done_key", (now as string) + "-" + Utility.RandomInt(0, 999999))
	JsonUtil.StringListAdd(path, "done_text", asLine)
	While JsonUtil.StringListCount(path, "done_key") > MaxKept()
		JsonUtil.StringListRemoveAt(path, "done_key", 0)
		JsonUtil.StringListRemoveAt(path, "done_text", 0)
	EndWhile
	JsonUtil.Save(path)
	MLW_Hub hub = Game.GetFormFromFile(0x000820, HubPlugin()) as MLW_Hub
	If hub
		hub.Log("hub", "console: " + asLine)
	EndIf
EndFunction

; For the report: the last runs on this save.
string Function ReportText() global
	string r = "on " + IsOn() + ", ConsoleUtil " + ToolVersion() + "\n"
	int i = 0
	While i < StorageUtil.StringListCount(None, "MLW_ConsoleLog")
		r += "  " + StorageUtil.StringListGet(None, "MLW_ConsoleLog", i) + "\n"
		i += 1
	EndWhile
	Return r
EndFunction

; Control characters and line breaks become spaces; spaces at both ends go.
string Function OneLine(string asText) global
	string out = ""
	int n = StringUtil.GetLength(asText)
	int i = 0
	While i < n
		string c = StringUtil.GetNthChar(asText, i)
		int code = StringUtil.AsOrd(c)
		If code < 32 || code == 127
			out += " "
		Else
			out += c
		EndIf
		i += 1
	EndWhile
	int first = 0
	n = StringUtil.GetLength(out)
	While first < n && StringUtil.GetNthChar(out, first) == " "
		first += 1
	EndWhile
	int last = n - 1
	While last >= first && StringUtil.GetNthChar(out, last) == " "
		last -= 1
	EndWhile
	If last < first
		Return ""
	EndIf
	Return StringUtil.Substring(out, first, last - first + 1)
EndFunction

string Function Joined(string[] akItems, int aiCount) global
	string out = ""
	int i = 0
	While i < aiCount
		If i > 0
			out += " ; "
		EndIf
		out += akItems[i]
		i += 1
	EndWhile
	Return out
EndFunction

string Function Short(string asText, int aiMax) global
	If StringUtil.GetLength(asText) > aiMax
		Return StringUtil.Substring(asText, 0, aiMax) + "..."
	EndIf
	Return asText
EndFunction
