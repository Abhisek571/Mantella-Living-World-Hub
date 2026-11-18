Scriptname MLW_Command Hidden
{Absolute Command: the hotkey (MCM, G by default) opens a text box during a Mantella conversation. What the player
types is an absolute command for every NPC in that conversation (never a child): it is written to
SKSE/Plugins/StorageUtilData/MantellaLivingWorld/commands.json, where the Hub's side in Mantella reads it, keeps it per
NPC and puts it above everything else in their prompt (a command to forget something hides those memories). Then
Mantella is asked for an NPC turn, so they answer it without the player speaking (needs Mantella - Direct AI Connect;
without it they answer at the player's next reply). The key is read by MLW_Setup, which owns the hub's hotkeys.
Each NPC given a command counts as close and intimate for the game side's re-checks (MLW_CommandUntil, read by
MLW_Channel.Commanded) for the Commands last setting, or one game day when that is 0, from their newest command.}

string Function FilePath() global
	Return "MantellaLivingWorld/commands.json"
EndFunction

; Commands kept in the file; the Hub's side remembers which ones it has read.
int Function MaxQueued() global
	Return 20
EndFunction

; Commands last (game hours) as Mantella's side wrote it; 0 (until removed there) counts as one game day here.
float Function FlagDays() global
	string path = "MantellaLivingWorld/command_settings.json"
	JsonUtil.Unload(path, false, false)  ; Mantella's side rewrites it when the setting changes: Load alone keeps the old copy
	JsonUtil.Load(path)
	int hours = JsonUtil.GetIntValue(path, "command_hours", 0)
	If hours <= 0
		Return 1.0
	EndIf
	Return (hours as float) / 24.0
EndFunction

; Every NPC in this conversation the command was given to (their ref ids in asRefs) counts as close and intimate until
; asNow + FlagDays(); a newer command renews it. Never a child.
Function FlagNpcs(MantellaConversation akTalk, MLW_Channel akChannel, string asRefs, float afNow) global
	float until = afNow + FlagDays()
	string refs = "," + asRefs + ","
	Actor player = Game.GetPlayer()
	int i = 0
	While i < akTalk.CountActorsInConversation()
		Actor npc = akTalk.GetActorInConversationByIndex(i)
		If npc && npc != player && !akChannel.IsMinor(npc) && !akChannel.NpcFlag(npc, "ignore_commands") && StringUtil.Find(refs, "," + akChannel.Hex(npc.GetFormID()) + ",") >= 0
			StorageUtil.SetFloatValue(npc, "MLW_CommandUntil", until)
		EndIf
		i += 1
	EndWhile
EndFunction

Function Give() global
	MantellaConversation talk = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	MLW_Channel channel = Game.GetFormFromFile(0x000823, "Mantella Living World - Integration Hub.esp") as MLW_Channel
	If !talk || !channel || !talk.IsRunning()
		Debug.Notification("Absolute Command: start a Mantella conversation first.")
		Return
	EndIf
	Actor player = Game.GetPlayer()
	string refs = ""
	string names = ""
	int i = 0
	While i < talk.CountActorsInConversation()
		Actor npc = talk.GetActorInConversationByIndex(i)
		If npc && npc != player && !channel.IsMinor(npc) && !channel.NpcFlag(npc, "ignore_commands")
			If refs != ""
				refs += ","
				names += "|"
			EndIf
			refs += channel.Hex(npc.GetFormID())
			names += npc.GetDisplayName()
		EndIf
		i += 1
	EndWhile
	If refs == ""
		Debug.Notification("Absolute Command: nobody in this conversation can be given one.")
		Return
	EndIf
	UIExtensions.InitMenu("UITextEntryMenu")
	UIExtensions.OpenMenu("UITextEntryMenu")
	string text = UIExtensions.GetMenuResultString("UITextEntryMenu")
	If !HasText(text) || !talk.IsRunning()
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
	While JsonUtil.StringListCount(path, "key") > MaxQueued()
		JsonUtil.StringListRemoveAt(path, "key", 0)
		JsonUtil.StringListRemoveAt(path, "text", 0)
		JsonUtil.StringListRemoveAt(path, "refs", 0)
		JsonUtil.StringListRemoveAt(path, "names", 0)
		JsonUtil.StringListRemoveAt(path, "time", 0)
		JsonUtil.StringListRemoveAt(path, "player", 0)
	EndWhile
	JsonUtil.Save(path)
	FlagNpcs(talk, channel, refs, now)
	string shown = StringUtil.Substring(text, 0, 60)
	If StringUtil.GetLength(text) > 60
		shown += "..."
	EndIf
	Debug.Notification("Absolute Command: " + shown)
	MLW_Hub hub = Game.GetFormFromFile(0x000820, "Mantella Living World - Integration Hub.esp") as MLW_Hub
	If hub
		hub.Log("hub", "absolute command for " + names + ": " + text)
	EndIf
	AskForTurn(talk, channel, player.GetDisplayName() + " looks at " + ListNames(names) + ".")
EndFunction

; Once Mantella waits for the player (an NPC may still be speaking, up to 30 seconds), a neutral in-game event and an
; event-only turn: the NPCs answer the command now. The event says nothing about the command itself.
Function AskForTurn(MantellaConversation akTalk, MLW_Channel akChannel, string asEvent) global
	int tries = 0
	While (!akChannel.AwaitingPlayer() || akTalk.GetIsTalking()) && tries < 60 && akTalk.IsRunning()
		Utility.Wait(0.5)
		tries += 1
	EndWhile
	If !akTalk.IsRunning() || !akChannel.AwaitingPlayer() || akTalk.GetIsTalking()
		Return  ; they answer it at the player's next reply
	EndIf
	akTalk.AddIngameEvent(asEvent)
	akChannel.TurnRequested()
	akTalk.AddExtraRequestAction("mantella_event_turn")
	; RequestContinueConversation(true) waits (up to 5 s) for an action result, then re-arms that wait for the next
	; action. Answer it first: sent after the call, it would cancel the next real action's wait instead.
	int done = ModEvent.Create("Mantella_ActionResponseCompleted")
	If done
		ModEvent.PushString(done, "mantella_event_turn")
		ModEvent.Send(done)
	EndIf
	akTalk.RequestContinueConversation(true)
EndFunction

bool Function HasText(string asText) global
	int i = 0
	int n = StringUtil.GetLength(asText)
	While i < n
		string c = StringUtil.GetNthChar(asText, i)
		If c != " " && c != "\t" && c != "\n"
			Return true
		EndIf
		i += 1
	EndWhile
	Return false
EndFunction

; "Lydia|Faendal|Uthgerd" -> "Lydia, Faendal and Uthgerd"
string Function ListNames(string asNames) global
	string[] parts = StringUtil.Split(asNames, "|")
	string out = ""
	int i = 0
	While i < parts.Length
		If i > 0 && i == parts.Length - 1
			out += " and "
		ElseIf i > 0
			out += ", "
		EndIf
		out += parts[i]
		i += 1
	EndWhile
	Return out
EndFunction
