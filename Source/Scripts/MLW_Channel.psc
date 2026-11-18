Scriptname MLW_Channel extends Quest
{The file channel: what Mantella's side needs to know about the NPCs in a conversation, written as PapyrusUtil
JSON under SKSE/Plugins/StorageUtilData/MantellaLivingWorld/ for the Living World extension in Mantella.

npc/<base id>.json: name, ref_id, close (see CloseStanding), intimate (see IntimateStanding), minor (1 for a child),
follower, guard, rated (OStim Expansion positions), and for the world note and the basic bio: hold (where they belong, see NpcHold),
location (where they are now), here_hold (the hold they are in now), race, sex, class, work (their vanilla job faction) and groups (the guilds and sides
World's quest outcomes are told to), and for the Characters page: rank, spouse, housecarl, allow_intimacy (Always willing), home and
factions (readable names). conversation.json: the player's name and the base ids of everyone in the current conversation. On its own quest:
SKSE keeps one mod event registration per object.

Modules send "MLW_RefreshNpc" (one Form) after they change what the file holds (Arousal after it works out how
close the NPC is, Relationships after an engagement, Followers after a join or leave), so the file is rewritten
during the talk instead of keeping what it held when the NPC joined.}

Actor Property PlayerRef Auto

string Property DIR = "MantellaLivingWorld/" AutoReadOnly
string Property CONVERSATION = "MantellaLivingWorld/conversation.json" AutoReadOnly
; Written by Mantella's side: the Characters page flags ("<name>|<flag>" = 1, by display name) and the Intimacy setting
; (0 Lovers only, 1 NPC decides; 2 from an older version is NPC decides), which the MCM writes too (SetIntimacyCheck).
string Property FLAGS = "MantellaLivingWorld/npc_flags.json" AutoReadOnly
string Property INTIMACY = "MantellaLivingWorld/intimacy_settings.json" AutoReadOnly

Event OnInit()
	Register()
EndEvent

Function Register()
	RegisterForModEvent("MantellaConversation_Started", "OnStarted")
	RegisterForModEvent("MantellaConversation_NPC_Added", "OnNpcAdded")
	RegisterForModEvent("MantellaConversation_NPC_Removed", "OnNpcRemoved")
	RegisterForModEvent("MantellaConversation_Ended", "OnEnded")
	RegisterForModEvent("MantellaConversation_Action_mantella_remove_character", "OnRemoveCharacter")
	RegisterForModEvent("MLW_RefreshNpc", "OnRefreshNpc")
	RegisterForModEvent("SKSE_HTTP_OnHttpReplyReceived", "OnMantellaReply")
	RegisterForModEvent("MantellaConversation_Advanced_Action_mantella_mlwh_console", "OnConsoleAction")
	registeredVersion = REGISTER_VERSION
	ApplyPerf()
EndFunction

; Raised when Register() gains an event: a join re-registers only on a save made before that (not on every join).
int Property REGISTER_VERSION = 2 AutoReadOnly
int registeredVersion = 0

; ---------------------------------------------------------------------------
; Speed testing (MLW_Timing; off by default): stage times and preparing an NPC's file ahead of the talk
; ---------------------------------------------------------------------------

; A prepared file counts at talk start for this many game days (about 4 real minutes at the default time scale), and
; only while the NPC is still in the location they were prepared in; waiting or sleeping makes it stale.
float Property PREPARE_FRESH_DAYS = 0.05 AutoReadOnly
bool preparing = false
Actor preparingNpc = None
Actor aimedNpc = None
bool joining = false
float Property PREPARE_AIM_SECONDS = 1.5 AutoReadOnly
float Property PREPARE_DISTANCE = 600.0 AutoReadOnly
bool crosshairRegistered = false
int timingKey = -1

; Reads the switches (perf.json) and registers for what they need: the talk key for stage times, the crosshair for
; preparing. Called when an NPC joins and when a talk ends, so a change on the Settings page applies without a restart.
Function ApplyPerf()
	MLW_Timing.ReadSettings()
	int wanted = -1
	If MLW_Timing.On()
		MantellaRepository repo = Game.GetFormFromFile(0x000D62, "Mantella.esp") as MantellaRepository
		If repo
			wanted = repo.MantellaStartHotkey
		EndIf
	EndIf
	If wanted != timingKey
		If timingKey > 0
			UnregisterForKey(timingKey)
		EndIf
		If wanted > 0
			RegisterForKey(wanted)
		EndIf
		timingKey = wanted
	EndIf
	If MLW_Timing.PrepareOn() != crosshairRegistered  ; registered or not only when the switch changed
		crosshairRegistered = MLW_Timing.PrepareOn()
		If crosshairRegistered
			RegisterForCrosshairRef()
		Else
			UnregisterForCrosshairRef()
		EndIf
	EndIf
EndFunction

Event OnKeyDown(int aiKeyCode)
	If aiKeyCode == timingKey && MLW_Timing.On() && !Utility.IsInMenuMode()
		MLW_Timing.NewTalk("talk_key")
	EndIf
EndEvent

; The player aims at an NPC: their file is written now (the same WriteNpc a talk start runs), so a talk start soon
; after only refreshes what changes from moment to moment (WriteNpcChanging). Bounded: only an NPC under the
; crosshair, not in combat or a menu, one at a time, and at most once per NPC per PREPARE_FRESH_DAYS.
Event OnCrosshairRefChange(ObjectReference akRef)
	Actor npc = akRef as Actor
	If !npc || npc == PlayerRef || preparing || joining || !MLW_Timing.PrepareOn() || PreparedFresh(npc)
		aimedNpc = None
		Return
	EndIf
	aimedNpc = npc  ; prepared only if the player is still aiming at them a moment later (OnUpdate)
	RegisterForSingleUpdate(PREPARE_AIM_SECONDS)
EndEvent

Event OnUpdate()
	Actor npc = aimedNpc
	aimedNpc = None
	If !npc || preparing || joining || Game.GetCurrentCrosshairRef() != npc || PreparedFresh(npc)
		Return
	EndIf
	If npc.IsDead() || PlayerRef.IsInCombat() || Utility.IsInMenuMode() || npc.GetDistance(PlayerRef) > PREPARE_DISTANCE || InMantellaTalk(npc)
		Return
	EndIf
	preparing = true
	preparingNpc = npc
	MLW_Timing.Mark("hub", "prepare_start", npc.GetDisplayName())
	WriteNpc(npc, BaseId(npc))
	StorageUtil.SetFloatValue(npc, "MLW_PreparedAt", Utility.GetCurrentGameTime())
	StorageUtil.SetFormValue(npc, "MLW_PreparedLoc", npc.GetCurrentLocation())
	MLW_Timing.Mark("hub", "prepare_end", npc.GetDisplayName())
	preparingNpc = None
	preparing = false
EndEvent

; Prepared within PREPARE_FRESH_DAYS of game time (never in the future: an older save loaded) and in the same place.
bool Function PreparedFresh(Actor akNpc)
	float at = StorageUtil.GetFloatValue(akNpc, "MLW_PreparedAt", -1.0)
	If at < 0.0
		Return false
	EndIf
	float age = Utility.GetCurrentGameTime() - at
	Return age >= 0.0 && age <= PREPARE_FRESH_DAYS && StorageUtil.GetFormValue(akNpc, "MLW_PreparedLoc") == akNpc.GetCurrentLocation()
EndFunction

; At talk start with a fresh prepared file: only what can change from moment to moment (standing with the player, a
; follower, a scene rated, the Characters page flags, marriage and home). Who they are, their factions, jobs and
; groups, hold, race, class and magic come from the prepared file. The mod facts were written just before
; (WriteMinorFirst). Fields left out here are all written by WriteNpc, so both paths fill the same fields.
Function WriteNpcChanging(Actor akNpc, string asId)
	string path = DIR + "npc/" + asId + ".json"
	ClaimFile(akNpc, path)  ; a refresh (OnRefreshNpc) can come for an NPC whose file another plugin's NPC holds
	JsonUtil.SetStringValue(path, "name", akNpc.GetDisplayName())
	JsonUtil.SetStringValue(path, "ref_id", Hex(akNpc.GetFormID()))
	JsonUtil.SetIntValue(path, "close", CloseStanding(akNpc))
	JsonUtil.SetIntValue(path, "intimate", IntimateStanding(akNpc))
	JsonUtil.SetIntValue(path, "follower", IsFollower(akNpc) as int)
	JsonUtil.SetIntValue(path, "rated", StorageUtil.GetIntValue(akNpc, "MAE_PosesRated", 0))
	JsonUtil.SetIntValue(path, "rank", akNpc.GetRelationshipRank(PlayerRef))
	JsonUtil.SetIntValue(path, "spouse", InFaction(akNpc, 0x0C6472, "Skyrim.esm") as int)  ; PlayerMarriedFaction
	JsonUtil.SetIntValue(path, "housecarl", InFaction(akNpc, 0x0A2C8D, "Skyrim.esm") as int)  ; PlayerHousecarlFaction
	JsonUtil.SetIntValue(path, "allow_intimacy", StorageUtil.GetIntValue(akNpc, "MLW_Intimate", 0))
	JsonUtil.SetStringValue(path, "home", NpcHome(akNpc, path))
	bool tradesFree = NpcFlag(akNpc, "trades_without_asking")
	JsonUtil.SetIntValue(path, "trades_free", tradesFree as int)
	If tradesFree
		StorageUtil.SetIntValue(akNpc, "MLW_TradesFree", 1)
	Else
		StorageUtil.UnsetIntValue(akNpc, "MLW_TradesFree")
	EndIf
	JsonUtil.SetStringValue(path, "player", PlayerRef.GetDisplayName())  ; whose standing this is (every save shares the file)
	JsonUtil.Save(path)
EndFunction

; The Console button's action (MLW_Console.Run): the commands the model wrote for the player's wish, run only after
; the player picks Run in the box that lists them.
Event OnConsoleAction(Form akSpeaker, Form akConversation, int aiArguments)
	MLW_Console.Run(SKSE_HTTP.getStringArray(aiArguments, "commands"), SKSE_HTTP.getString(aiArguments, "summary", ""))
EndEvent

; Absolute Command (MLW_Command) asks for an NPC turn only while Mantella waits for the player, as known from Mantella's
; own replies.
bool awaitingPlayer = false

Event OnMantellaReply(int aiHandle)
	awaitingPlayer = SKSE_HTTP.getString(aiHandle, "mantella_reply_type", "") == "mantella_player_talk"
EndEvent

bool Function AwaitingPlayer()
	Return awaitingPlayer
EndFunction

Function TurnRequested()
	awaitingPlayer = false
EndFunction

; A module changed what it tells the file (Arousal's standing, M.A.R.A.S, a follower joining): only the fields that
; change from moment to moment are written again (WriteNpcChanging), not the whole file.
Event OnRefreshNpc(Form akActor)
	Actor npc = akActor as Actor
	If npc && npc != PlayerRef
		WriteNpcChanging(npc, BaseId(npc))
	EndIf
EndEvent

; "Goodbye <name>" in a group talk: Mantella sends this action with only the speaker, but its own handler expects a
; second value and so never runs; the NPC stays in the talk. Removing them here does what that handler meant to do.
; (One-on-one goodbyes are ended by Mantella - Direct AI Connect.)
Event OnRemoveCharacter(Form akSpeaker)
	MantellaConversation c = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	Actor npc = akSpeaker as Actor
	If c && c.IsRunning() && npc && npc != PlayerRef
		Actor[] leaving = new Actor[1]
		leaving[0] = npc
		c.RemoveActorsFromConversation(leaving)
	EndIf
EndEvent

; The Ended event does not always arrive, and Started comes after the first NPC_Added, so a new conversation drops
; everyone who joined more than 30 seconds before it started (left over from an earlier talk).
Event OnStarted()
	MLW_Timing.Mark("hub", "started_request_sent")  ; Mantella sends this event right after the start request
	ApplyPerf()  ; a Settings page change applies from this talk on
	ReadMantellaSide()
	; the file is saved here before the speakers are written: its player line must already be this character's, or the
	; first talk after loading another character's save reads the previous name from the newest file
	JsonUtil.SetStringValue(CONVERSATION, "player", PlayerRef.GetDisplayName())
	JsonUtil.SetIntValue(CONVERSATION, "day", Utility.GetCurrentGameTime() as int)  ; the same: a stale day would hide a newer world.json
	; the MCM's debug log switch, for the Hub's side too (it then logs which game facts went into the prompt)
	GlobalVariable debugLog = Game.GetFormFromFile(0x000809, "Mantella Living World - Integration Hub.esp") as GlobalVariable  ; MLW_DebugLog
	If debugLog
		JsonUtil.SetIntValue(CONVERSATION, "debug_log", debugLog.GetValueInt())
	EndIf
	MLW_Timeline.TalkStarted(CONVERSATION)  ; once per Mantella talk; closes a talk left open (missed Ended)
	float now = Utility.GetCurrentRealTime()
	int i = StorageUtil.FormListCount(self, "MLW_Speakers")
	While i > 0
		i -= 1
		Form npc = StorageUtil.FormListGet(self, "MLW_Speakers", i)
		float age = now - StorageUtil.GetFloatValue(npc, "MLW_SpeakerAdded", -1000.0)
		If age < 0.0 || age > 30.0
			StorageUtil.FormListRemoveAt(self, "MLW_Speakers", i)
		EndIf
	EndWhile
	WriteSpeakers()
EndEvent

Event OnNpcAdded(Form akActor)
	Actor npc = akActor as Actor
	If !npc || npc == PlayerRef
		Return
	EndIf
	If registeredVersion != REGISTER_VERSION
		Register()  ; saves that started this quest before an event was added never ran OnInit again
	EndIf
	joining = true
	If MLW_Timing.On()
		If Utility.GetCurrentRealTime() - StorageUtil.GetFloatValue(None, "MLW_TimingTalkAt", -1000.0) > 15.0
			MLW_Timing.NewTalk("first_join_no_key")  ; a talk started by a spell, another mod or a radiant talk
		EndIf
		MLW_Timing.Mark("hub", "npc_added_start", npc.GetDisplayName())
	EndIf
	WriteMinorFirst(npc, BaseId(npc))  ; before anything slow: Mantella's first request is already on its way
	ReadMantellaSide()
	If MLW_Timing.PrepareOn() && PreparedFresh(npc) && preparingNpc != npc  ; a prepare still running: the full write
		WriteNpcChanging(npc, BaseId(npc))
		MLW_Timing.Mark("hub", "npc_file_prepared_path", npc.GetDisplayName())
	Else
		WriteNpc(npc, BaseId(npc))
		MLW_Timing.Mark("hub", "npc_file_full_path", npc.GetDisplayName())
	EndIf
	If PlayerInTalk()
		StorageUtil.SetFormValue(None, "MLW_LastNpc", npc)  ; the MCM's cheats page targets them when nobody is aimed at
	EndIf
	float now = Utility.GetCurrentRealTime()
	; Started comes after the first NPC_Added, so someone left from a talk that never ended would count as a speaker
	; in this NPC's first reply: drop anyone who joined more than 30 seconds ago and is not in Mantella's talk now.
	; Mantella sends NPC_Added only for newcomers, so the people already talking must stay (a child among them keeps
	; every close or intimate action out).
	int i = StorageUtil.FormListCount(self, "MLW_Speakers")
	While i > 0
		i -= 1
		Form old = StorageUtil.FormListGet(self, "MLW_Speakers", i)
		float age = now - StorageUtil.GetFloatValue(old, "MLW_SpeakerAdded", -1000.0)
		If old != npc && (age < 0.0 || age > 30.0) && !InMantellaTalk(old as Actor)
			StorageUtil.FormListRemoveAt(self, "MLW_Speakers", i)
		EndIf
	EndWhile
	StorageUtil.SetFloatValue(npc, "MLW_SpeakerAdded", now)
	StorageUtil.FormListAdd(self, "MLW_Speakers", npc, false)
	WriteSpeakers()
	joining = false
	MLW_Timing.Mark("hub", "npc_added_end", npc.GetDisplayName())
EndEvent

Event OnNpcRemoved(Form akActor)
	StorageUtil.FormListRemove(self, "MLW_Speakers", akActor, true)
	WriteSpeakers()
EndEvent

; The Ended event of a talk can arrive after the next talk has already added its first NPC (a new talk started within
; seconds): keep whoever is in Mantella's running conversation, so that talk keeps its speakers and gates.
Event OnEnded()
	awaitingPlayer = false
	JsonUtil.SetStringValue(CONVERSATION, "player", PlayerRef.GetDisplayName())  ; saved below with the counter
	JsonUtil.SetIntValue(CONVERSATION, "day", Utility.GetCurrentGameTime() as int)
	MLW_Timeline.TalkEnded(CONVERSATION)
	ApplyPerf()  ; a Settings page change applies from the next talk
	int i = StorageUtil.FormListCount(self, "MLW_Speakers")
	While i > 0
		i -= 1
		If !InMantellaTalk(StorageUtil.FormListGet(self, "MLW_Speakers", i) as Actor)
			StorageUtil.FormListRemoveAt(self, "MLW_Speakers", i)
		EndIf
	EndWhile
	WriteSpeakers()
EndEvent

Function WriteSpeakers()
	int i = StorageUtil.FormListCount(self, "MLW_Speakers")
	While i > 0
		i -= 1
		Actor gone = StorageUtil.FormListGet(self, "MLW_Speakers", i) as Actor
		If !gone || gone.IsDead()
			StorageUtil.FormListRemoveAt(self, "MLW_Speakers", i)
		EndIf
	EndWhile
	JsonUtil.StringListClear(CONVERSATION, "speakers")
	int count = StorageUtil.FormListCount(self, "MLW_Speakers")
	i = 0
	While i < count
		JsonUtil.StringListAdd(CONVERSATION, "speakers", BaseId(StorageUtil.FormListGet(self, "MLW_Speakers", i) as Actor), false)  ; no duplicates when two joins write at once
		i += 1
	EndWhile
	JsonUtil.SetStringValue(CONVERSATION, "player", PlayerRef.GetDisplayName())
	JsonUtil.SetIntValue(CONVERSATION, "day", Utility.GetCurrentGameTime() as int)  ; so NPCs know how long it has been
	GlobalVariable setupDone = Game.GetFormFromFile(0x000807, "Mantella Living World - Integration Hub.esp") as GlobalVariable  ; MLW_SetupDone
	If setupDone
		JsonUtil.SetIntValue(CONVERSATION, "setup_done", setupDone.GetValueInt())  ; for the Main Status tab
	EndIf
	MLW_Timeline.Write(CONVERSATION)  ; the talk counter, so memories made after a save roll back when it is loaded
	MLW_WorldFacts.WritePlayer(CONVERSATION)  ; the player's Illusion skill, for who can tell a spell is at work
	JsonUtil.Save(CONVERSATION)
EndFunction

; A newly met NPC's file with just who they are and whether they are a child, saved at once, so the extension can
; trust their age already at the greeting (WriteNpc then writes the rest). The mod facts follow, then a second save.
; The minor flag is always this NPC's own: the file is named by the last 6 hex digits only, so another plugin's NPC
; can share it (ClaimFile).
Function WriteMinorFirst(Actor akNpc, string asId)
	string path = DIR + "npc/" + asId + ".json"
	ClaimFile(akNpc, path)
	JsonUtil.SetStringValue(path, "name", akNpc.GetDisplayName())
	JsonUtil.SetStringValue(path, "ref_id", Hex(akNpc.GetFormID()))
	JsonUtil.SetIntValue(path, "minor", IsMinor(akNpc) as int)
	JsonUtil.Save(path)
	; the other mods' facts too, here: the first prompt is built before WriteNpc's slower part is saved (live test 14)
	MLW_ModFacts.WriteNpc(akNpc, path)
	JsonUtil.Save(path)
EndFunction

; npc/<6 hex>.json is shared by NPCs of different plugins whose base ids end in the same digits (xx000801 and
; yy000801, or a light plugin's FE id). The file keeps the full base id (base_full); when it names another NPC, all of
; that NPC's values are cleared, so nothing (a child flag, standing, facts) carries over. A file from an older version
; has no base_full and is kept.
Function ClaimFile(Actor akNpc, string asPath)
	string full = Hex(akNpc.GetActorBase().GetFormID())
	string stored = JsonUtil.GetStringValue(asPath, "base_full", "")
	If stored != "" && stored != full
		JsonUtil.ClearAll(asPath)
		StorageUtil.UnsetFloatValue(akNpc, "MLW_PreparedAt")  ; the prepared static part went with it: written again in full
	EndIf
	JsonUtil.SetStringValue(asPath, "base_full", full)
EndFunction

Function WriteNpc(Actor akNpc, string asId)
	string path = DIR + "npc/" + asId + ".json"
	ClaimFile(akNpc, path)  ; also from the crosshair prepare, before any join
	JsonUtil.SetStringValue(path, "name", akNpc.GetDisplayName())
	JsonUtil.SetStringValue(path, "ref_id", Hex(akNpc.GetFormID()))
	JsonUtil.SetIntValue(path, "close", CloseStanding(akNpc))  ; Mantella's side adds absolute commands itself, and ends them
	JsonUtil.SetIntValue(path, "intimate", IntimateStanding(akNpc))
	JsonUtil.SetIntValue(path, "minor", IsMinor(akNpc) as int)
	JsonUtil.SetIntValue(path, "follower", IsFollower(akNpc) as int)
	JsonUtil.SetIntValue(path, "guard", akNpc.IsGuard() as int)
	; who may settle a bounty or take a crime report (World's MLWW_Crime.IsAuthority): a guard, a Jarl or a steward
	JsonUtil.SetIntValue(path, "authority", (akNpc.IsGuard() || InFaction(akNpc, 0x050920, "Skyrim.esm") || InFaction(akNpc, 0x050922, "Skyrim.esm")) as int)  ; JobJarlFaction, JobStewardFaction
	JsonUtil.SetIntValue(path, "rated", StorageUtil.GetIntValue(akNpc, "MAE_PosesRated", 0))
	; for the Characters page facts: rank with the player, the vanilla marriage, the player's housecarl, the hotkey's
	; Always willing, where they live now
	JsonUtil.SetIntValue(path, "rank", akNpc.GetRelationshipRank(PlayerRef))
	JsonUtil.SetIntValue(path, "spouse", InFaction(akNpc, 0x0C6472, "Skyrim.esm") as int)  ; PlayerMarriedFaction
	JsonUtil.SetIntValue(path, "housecarl", InFaction(akNpc, 0x0A2C8D, "Skyrim.esm") as int)  ; PlayerHousecarlFaction
	JsonUtil.SetIntValue(path, "allow_intimacy", StorageUtil.GetIntValue(akNpc, "MLW_Intimate", 0))
	JsonUtil.SetStringValue(path, "home", NpcHome(akNpc, path))
	; Trades without asking (Characters page), for World's trading: the npc file and the actor both carry it
	bool tradesFree = NpcFlag(akNpc, "trades_without_asking")
	JsonUtil.SetIntValue(path, "trades_free", tradesFree as int)
	If tradesFree
		StorageUtil.SetIntValue(akNpc, "MLW_TradesFree", 1)
	Else
		StorageUtil.UnsetIntValue(akNpc, "MLW_TradesFree")
	EndIf
	JsonUtil.SetStringValue(path, "player", PlayerRef.GetDisplayName())  ; whose standing this is (every save shares the file)
	WriteWho(akNpc, path)
	MLW_WorldFacts.WriteNpc(akNpc, path)  ; Illusion skill, magic training, town and home town (world news)
	; the mod facts (modfacts/ files) are written by WriteMinorFirst at every join, once
	JsonUtil.Save(path)
EndFunction

; ---------------------------------------------------------------------------
; Who the NPC is: hold, place, race, sex, class, job and groups (vanilla records, Skyrim.esm)
; ---------------------------------------------------------------------------

string[] holdNames
Location[] holdLocs
Faction[] holdCrime
string[] workNames
Faction[] workFacs
string[] groupNames
Faction[] groupFacs

Function WriteWho(Actor akNpc, string asPath)
	SetupWho()
	ActorBase base = akNpc.GetActorBase()
	JsonUtil.SetStringValue(asPath, "hold", NpcHold(akNpc))
	Location here = akNpc.GetCurrentLocation()
	string place = ""
	If here
		place = here.GetName()
	EndIf
	JsonUtil.SetStringValue(asPath, "location", place)
	string hereHold = ""
	int h = HoldOfLocation(here)
	If h >= 0
		hereHold = holdNames[h]
	EndIf
	JsonUtil.SetStringValue(asPath, "here_hold", hereHold)
	string raceName = ""
	If akNpc.GetRace()
		raceName = akNpc.GetRace().GetName()
	EndIf
	JsonUtil.SetStringValue(asPath, "race", raceName)
	string sex = "male"
	If akNpc.GetLeveledActorBase().GetSex() == 1  ; leveled and templated NPCs take their sex from the template
		sex = "female"
	EndIf
	JsonUtil.SetStringValue(asPath, "sex", sex)
	string cls = ""
	If base.GetClass()
		cls = base.GetClass().GetName()
	EndIf
	JsonUtil.SetStringValue(asPath, "class", cls)
	string work = ""
	int i = 0
	While i < workFacs.Length && work == ""
		If workFacs[i] && akNpc.IsInFaction(workFacs[i])
			work = workNames[i]
		EndIf
		i += 1
	EndWhile
	JsonUtil.SetStringValue(asPath, "work", work)
	JsonUtil.StringListClear(asPath, "groups")
	i = 0
	While i < groupFacs.Length
		If groupFacs[i] && akNpc.IsInFaction(groupFacs[i])
			JsonUtil.StringListAdd(asPath, "groups", groupNames[i], false)
		EndIf
		i += 1
	EndWhile
	SetupFactions()
	JsonUtil.StringListClear(asPath, "factions")
	i = 0
	While i < factionFacs.Length
		If factionFacs[i] && akNpc.IsInFaction(factionFacs[i])
			JsonUtil.StringListAdd(asPath, "factions", factionNames[i], false)  ; two temple factions share a name
		EndIf
		i += 1
	EndWhile
EndFunction

; The readable faction names Mantella's side shows on the Characters page ("Member of"), vanilla and DLC.
string[] factionNames
Faction[] factionFacs

Function SetupFactions()
	If factionFacs && factionFacs.Length == 25 && factionFacs[0]
		Return
	EndIf
	factionNames = new string[25]
	factionFacs = new Faction[25]
	SetFaction(0, "Companions", 0x048362, "Skyrim.esm")
	SetFaction(1, "The Circle", 0x0FF234, "Skyrim.esm")
	SetFaction(2, "Thieves Guild", 0x029DA9, "Skyrim.esm")
	SetFaction(3, "Dark Brotherhood", 0x01BDB3, "Skyrim.esm")
	SetFaction(4, "Stormcloaks", 0x02BF9B, "Skyrim.esm")
	SetFaction(5, "Imperial Legion", 0x02BF9A, "Skyrim.esm")
	SetFaction(6, "College of Winterhold", 0x01F259, "Skyrim.esm")
	SetFaction(7, "Thalmor", 0x039F26, "Skyrim.esm")
	SetFaction(8, "Forsworn", 0x043599, "Skyrim.esm")
	SetFaction(9, "Blades", 0x072834, "Skyrim.esm")
	SetFaction(10, "Greybeards", 0x02C6C8, "Skyrim.esm")
	SetFaction(11, "Penitus Oculatus", 0x02584B, "Skyrim.esm")
	SetFaction(12, "Silver Hand", 0x0AA0A4, "Skyrim.esm")
	SetFaction(13, "Vigilants of Stendarr", 0x0B3292, "Skyrim.esm")
	SetFaction(14, "Bards College", 0x0C13C7, "Skyrim.esm")
	SetFaction(15, "Temple of the Divines", 0x0C13FD, "Skyrim.esm")
	SetFaction(16, "Temple of Kynareth", 0x0ECC44, "Skyrim.esm")
	SetFaction(17, "Temple of Mara", 0x0A2526, "Skyrim.esm")
	SetFaction(18, "Temple of Dibella", 0x0656EA, "Skyrim.esm")
	SetFaction(19, "Temple of Talos", 0x103961, "Skyrim.esm")  ; WindhelmTempleFaction
	SetFaction(20, "Priests of Arkay", 0x0C139A, "Skyrim.esm")  ; Falkreath's Hall of the Dead
	SetFaction(21, "Priests of Arkay", 0x0F122C, "Skyrim.esm")  ; Markarth's Hall of the Dead
	SetFaction(22, "Dawnguard", 0x014217, "Dawnguard.esm")
	SetFaction(23, "Volkihar vampires", 0x003376, "Dawnguard.esm")
	SetFaction(24, "Morag Tong", 0x02929A, "Dragonborn.esm")
EndFunction

Function SetFaction(int aiIndex, string asName, int aiFaction, string asPlugin)
	factionNames[aiIndex] = asName
	If Loaded(asPlugin)
		factionFacs[aiIndex] = Game.GetFormFromFile(aiFaction, asPlugin) as Faction
	EndIf
EndFunction

bool Function InFaction(Actor akNpc, int aiFaction, string asPlugin)
	Faction f = Game.GetFormFromFile(aiFaction, asPlugin) as Faction
	Return f && akNpc.IsInFaction(f)
EndFunction

; Where they live: a spouse seen in a player home (LocTypePlayerHouse) lives there from then on (MLW_Home, kept on the
; actor until they are no longer married), else their editor location; "" when neither is known.
string Function NpcHome(Actor akNpc, string asPath)
	bool married = InFaction(akNpc, 0x0C6472, "Skyrim.esm") || JsonUtil.GetIntValue(asPath, "maras", 0) >= 3  ; PlayerMarriedFaction or M.A.R.A.S married (rank 4 is only Lover)
	If !married
		StorageUtil.UnsetStringValue(akNpc, "MLW_Home")
	Else
		Location here = akNpc.GetCurrentLocation()
		Keyword playerHouse = Game.GetFormFromFile(0x0FC1A3, "Skyrim.esm") as Keyword  ; LocTypePlayerHouse
		If here && playerHouse && here.HasKeyword(playerHouse) && here.GetName() != ""
			StorageUtil.SetStringValue(akNpc, "MLW_Home", here.GetName())
		EndIf
	EndIf
	string moved = StorageUtil.GetStringValue(akNpc, "MLW_Home")
	If moved != ""
		Return moved
	EndIf
	Location home = akNpc.GetEditorLocation()
	If home
		Return home.GetName()
	EndIf
	Return ""
EndFunction

; ---------------------------------------------------------------------------
; What Mantella's side decides: the Characters page flags and the Intimacy check
; ---------------------------------------------------------------------------

; Reads Mantella's side's files again (it rewrites them while the game runs: Load alone keeps the old copy), and brings
; the Intimacy setting in step on both sides (SyncIntimacy).
Function ReadMantellaSide()
	JsonUtil.Unload(FLAGS, false, false)
	JsonUtil.Load(FLAGS)
	JsonUtil.Unload(INTIMACY, false, false)
	JsonUtil.Load(INTIMACY)
	SyncIntimacy()
EndFunction

; Both sides change the Intimacy setting: Mantella's Settings page writes the shared file, the MCM sets the global (and
; writes the file through SetIntimacyCheck). MLW_IntimacySynced is the last value both sides agreed on, so it tells which
; side changed since: a file value that differs from it is Mantella's side's newer choice and goes into the global;
; otherwise a global that differs from the file (an MCM change whose file write did not happen, a reset MCM, a console
; SetGlobal) is written to the file. Called at talk start, when an NPC joins and when the MCM opens or closes.
Function SyncIntimacy()
	GlobalVariable check = IntimacyGlobal()
	If !check
		Return
	EndIf
	int mode = IntimacyMode()  ; an older Any adult (2) shows as NPC decides in the MCM
	If JsonUtil.HasIntValue(INTIMACY, "intimacy_check")
		int fileMode = JsonUtil.GetIntValue(INTIMACY, "intimacy_check", 1)
		If fileMode != 0
			fileMode = 1
		EndIf
		If fileMode != StorageUtil.GetIntValue(None, "MLW_IntimacySynced", -1)
			check.SetValueInt(fileMode)
			StorageUtil.SetIntValue(None, "MLW_IntimacySynced", fileMode)
			Return
		EndIf
		If fileMode == mode
			Return
		EndIf
	EndIf
	SetIntimacyCheck(mode)
EndFunction

; A Characters page flag for this NPC: bypass_intimacy (Intimacy: always willing), always_close, never_intimate
; (Intimacy: never), trades_without_asking, ignore_commands.
bool Function NpcFlag(Actor akNpc, string asFlag)
	Return akNpc && JsonUtil.GetIntValue(FLAGS, akNpc.GetDisplayName() + "|" + asFlag, 0) == 1
EndFunction

GlobalVariable Function IntimacyGlobal()
	Return Game.GetFormFromFile(0x00080E, "Mantella Living World - Integration Hub.esp") as GlobalVariable  ; MLW_IntimacyCheck
EndFunction

; The MCM's Intimacy setting changed: Mantella's side reads it from the shared file.
Function SetIntimacyCheck(int aiValue)
	JsonUtil.Unload(INTIMACY, false, false)
	JsonUtil.Load(INTIMACY)
	JsonUtil.SetIntValue(INTIMACY, "intimacy_check", aiValue)
	JsonUtil.Save(INTIMACY)
	StorageUtil.SetIntValue(None, "MLW_IntimacySynced", aiValue)
EndFunction

; The Intimacy setting, in one place so it can change: 1 NPC decides (every adult is offered the scene and decides in
; the talk; a no is a real result), 0 Lovers only (nothing more than the lover checks). The caller has already ruled out
; children and Intimacy: never.
bool Function IntimacyCheckPasses(Actor akNpc)
	Return IntimacyMode() == 1
EndFunction

; 0 Lovers only or 1 NPC decides (the default; also with no global). An older Any adult or Relaxed (2 or 1) is NPC
; decides, an older Strict (0) Lovers only; a 2 is written back as 1 so the MCM shows it.
int Function IntimacyMode()
	GlobalVariable check = IntimacyGlobal()
	If !check
		Return 1
	EndIf
	int mode = check.GetValueInt()
	If mode >= 2
		check.SetValueInt(1)
		Return 1
	EndIf
	If mode == 0
		Return 0
	EndIf
	Return 1
EndFunction

; The hold an NPC belongs to: their editor location's hold, else their crime faction's (as World works it out),
; else the hold they are in now; "" in no hold.
string Function NpcHold(Actor akNpc)
	int h = HoldOfLocation(akNpc.GetEditorLocation())
	Faction crime = akNpc.GetCrimeFaction()
	If h < 0 && crime
		h = holdCrime.Find(crime)
	EndIf
	If h < 0
		h = HoldOfLocation(akNpc.GetCurrentLocation())
	EndIf
	If h < 0
		Return ""
	EndIf
	Return holdNames[h]
EndFunction

int Function HoldOfLocation(Location akLocation)
	If !akLocation
		Return -1
	EndIf
	int i = 0
	While i < holdLocs.Length
		If holdLocs[i] && (akLocation == holdLocs[i] || holdLocs[i].IsChild(akLocation))
			Return i
		EndIf
		i += 1
	EndWhile
	Return -1
EndFunction

Function SetupWho()
	If groupFacs && groupFacs.Length == 9 && holdLocs[0]
		Return
	EndIf
	holdNames = new string[9]
	holdLocs = new Location[9]
	holdCrime = new Faction[9]
	SetHold(0, "Whiterun", 0x016772, 0x0267EA)
	SetHold(1, "Haafingar", 0x016770, 0x029DB0)
	SetHold(2, "Eastmarch", 0x01676A, 0x0267E3)
	SetHold(3, "Rift", 0x01676C, 0x02816B)
	SetHold(4, "Reach", 0x016769, 0x02816C)
	SetHold(5, "Pale", 0x01676D, 0x02816E)
	SetHold(6, "Falkreath", 0x01676F, 0x028170)
	SetHold(7, "Hjaalmarch", 0x01676E, 0x02816D)
	SetHold(8, "Winterhold", 0x01676B, 0x02816F)
	; first match wins, so the more telling jobs come first
	workNames = new string[16]
	workFacs = new Faction[16]
	SetWork(0, "jarl", 0x050920)
	SetWork(1, "steward", 0x050922)
	SetWork(2, "court wizard", 0x05091E)
	SetWork(3, "housecarl", 0x05091F)
	SetWork(4, "guard captain", 0x0813B7)
	SetWork(5, "priest", 0x05159A)
	SetWork(6, "innkeeper", 0x05091B)
	SetWork(7, "blacksmith", 0x05091D)
	SetWork(8, "apothecary", 0x05091C)
	SetWork(9, "fletcher", 0x051592)
	SetWork(10, "fence", 0x0806AA)
	SetWork(11, "bard", 0x053514)
	SetWork(12, "merchant", 0x051596)
	SetWork(13, "inn server", 0x0DEE93)
	SetWork(14, "farmer", 0x051591)
	SetWork(15, "miner", 0x051597)
	; group names as World's quest outcomes name their audience
	groupNames = new string[9]
	groupFacs = new Faction[9]
	SetGroup(0, "Companions", 0x048362)
	SetGroup(1, "College of Winterhold", 0x01F259)
	SetGroup(2, "Thieves Guild", 0x029DA9)
	SetGroup(3, "Dark Brotherhood", 0x01BDB3)
	SetGroup(4, "Greybeards", 0x02C6C8)
	SetGroup(5, "Blades", 0x072834)
	SetGroup(6, "Thalmor", 0x039F26)
	SetGroup(7, "Legion", 0x02BF9A)
	SetGroup(8, "Stormcloaks", 0x02BF9B)
EndFunction

Function SetHold(int aiIndex, string asName, int aiLocation, int aiCrimeFaction)
	holdNames[aiIndex] = asName
	holdLocs[aiIndex] = Game.GetFormFromFile(aiLocation, "Skyrim.esm") as Location
	holdCrime[aiIndex] = Game.GetFormFromFile(aiCrimeFaction, "Skyrim.esm") as Faction
EndFunction

Function SetWork(int aiIndex, string asName, int aiFaction)
	workNames[aiIndex] = asName
	workFacs[aiIndex] = Game.GetFormFromFile(aiFaction, "Skyrim.esm") as Faction
EndFunction

Function SetGroup(int aiIndex, string asName, int aiFaction)
	groupNames[aiIndex] = asName
	groupFacs[aiIndex] = Game.GetFormFromFile(aiFaction, "Skyrim.esm") as Faction
EndFunction

; Arousal's standing when it has one (1 close, 2 an open group); otherwise close for a vanilla friend or better, a
; teammate, or someone Relationships marks close (MRB_Close: engaged or married). Arousal sets its value in its own
; NPC_Added handler and then sends MLW_RefreshNpc, so a value left from the previous talk is replaced.
; A child is never close, whatever the rank or another module says. Close is friend-level; see IntimateValue.
; A module's value counts only while that module is installed: only it ever clears its value.
; An absolute command in force (Commanded) makes them close too; never a child. CloseStanding leaves commands out.
int Function CloseValue(Actor akNpc)
	int standing = CloseStanding(akNpc)
	If standing > 0
		Return standing
	EndIf
	If !IsMinor(akNpc) && Commanded(akNpc)
		Return 1
	EndIf
	Return 0
EndFunction

int Function CloseStanding(Actor akNpc)
	If IsMinor(akNpc)
		Return 0
	EndIf
	int standing = ArousalStanding(akNpc)
	If standing > 0
		Return standing
	EndIf
	If akNpc.GetRelationshipRank(PlayerRef) >= 1 || akNpc.IsPlayerTeammate() || RelationshipsClose(akNpc) > 0
		Return 1
	EndIf
	If NpcFlag(akNpc, "always_close")  ; ticked on Mantella's Characters page
		Return 1
	EndIf
	Return 0
EndFunction

; 1 when the intimate actions (OStim, Arousal) are offered for this NPC: with the Intimacy setting on NPC decides every
; adult (they say yes or no in the talk), on Lovers only a vanilla lover (rank 4), dating or closer in Relationships or
; an open group in Arousal; in both the player's own "Always willing" on the Living World hotkey (MLW_Intimate) or the
; Characters page. Intimacy: never shuts it. On Lovers only a friend, a follower or a forward temperament is close,
; never intimate.
; An absolute command in force (Commanded) makes them intimate too; never a child. IntimateStanding leaves commands out.
int Function IntimateValue(Actor akNpc)
	If IntimateStanding(akNpc) > 0
		Return 1
	EndIf
	If NpcFlag(akNpc, "never_intimate")  ; nothing overrides it, not even a command
		Return 0
	EndIf
	If !IsMinor(akNpc) && Commanded(akNpc)
		Return 1
	EndIf
	Return 0
EndFunction

int Function IntimateStanding(Actor akNpc)
	If IsMinor(akNpc)
		Return 0
	EndIf
	If NpcFlag(akNpc, "never_intimate")  ; Mantella's Characters page: never, whatever else says yes
		Return 0
	EndIf
	If akNpc.GetRelationshipRank(PlayerRef) >= 4 || RelationshipsClose(akNpc) > 0 || ArousalStanding(akNpc) == 2
		Return 1
	EndIf
	If StorageUtil.GetIntValue(akNpc, "MLW_Intimate", 0) == 1 || NpcFlag(akNpc, "bypass_intimacy")
		Return 1
	EndIf
	If IntimacyCheckPasses(akNpc)
		Return 1
	EndIf
	Return 0
EndFunction

; An absolute command overrides every limit: until the game time in MLW_CommandUntil (set by MLW_Command.Give) the
; game side's re-checks count the NPC as close and intimate. It ends only by time; removing the command on Mantella's
; side ends it there at once (the actions are no longer offered). A child is never commanded (IsMinor runs first).
bool Function Commanded(Actor akNpc)
	Return akNpc && StorageUtil.GetFloatValue(akNpc, "MLW_CommandUntil", 0.0) > Utility.GetCurrentGameTime() && !NpcFlag(akNpc, "ignore_commands")
EndFunction

; Arousal's MLW_IsClose while Arousal is installed; cleared when it is not, so a value frozen by an uninstall is gone.
int Function ArousalStanding(Actor akNpc)
	If Loaded("Mantella Living World - Arousal.esp")
		Return StorageUtil.GetIntValue(akNpc, "MLW_IsClose", 0)
	EndIf
	StorageUtil.UnsetIntValue(akNpc, "MLW_IsClose")
	Return 0
EndFunction

; Relationships' MRB_Close while Relationships is installed; cleared when it is not.
int Function RelationshipsClose(Actor akNpc)
	If Loaded("Mantella Living World - Relationships.esp")
		Return StorageUtil.GetIntValue(akNpc, "MRB_Close", 0)
	EndIf
	StorageUtil.UnsetIntValue(akNpc, "MRB_Close")
	Return 0
EndFunction

bool Function Loaded(string asPlugin)
	Return Game.GetModByName(asPlugin) != 255 || Game.GetLightModByName(asPlugin) != 65535
EndFunction

; True while the actor is one of the people in Mantella's running conversation.
bool Function InMantellaTalk(Actor akActor)
	MantellaConversation talk = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	If !akActor || !talk || !talk.IsRunning()
		Return false
	EndIf
	int i = talk.CountActorsInConversation()
	While i > 0
		i -= 1
		If talk.GetActorInConversationByIndex(i) == akActor
			Return true
		EndIf
	EndWhile
	Return false
EndFunction

bool Function PlayerInTalk()
	MantellaConversation talk = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	Return talk && talk.IsRunning() && talk.IsPlayerInConversation()
EndFunction

; Children are never close and get no temperament. Some mods clear the child flag, so the race is checked too.
bool Function IsMinor(Actor akActor)
	If akActor.IsChild()
		Return true
	EndIf
	Race actorRace = akActor.GetRace()
	Return actorRace && StringUtil.Find(MiscUtil.GetRaceEditorID(actorRace), "Child") >= 0
EndFunction

; In the party: a teammate or hired (CurrentFollowerFaction rank 0 or more; dismissed is -1). A potential follower is not.
bool Function IsFollower(Actor akNpc)
	If akNpc.IsPlayerTeammate()
		Return true
	EndIf
	Faction current = Game.GetFormFromFile(0x05C84E, "Skyrim.esm") as Faction
	Return current && akNpc.GetFactionRank(current) >= 0
EndFunction

; The base record's FormID as its last 6 hex digits, like Mantella's base_id (and the World module's npc files).
; Not the leveled base: for leveled NPCs that is a temporary form shared by unrelated people.
string Function BaseId(Actor akNpc)
	Return StringUtil.Substring(Hex(akNpc.GetActorBase().GetFormID()), 2)
EndFunction

string Function Hex(int aiValue)
	string digits = "0123456789ABCDEF"
	string out = ""
	int i = 0
	While i < 8
		int nibble = Math.LogicalAnd(Math.RightShift(aiValue, 28 - i * 4), 15)
		out += StringUtil.GetNthChar(digits, nibble)
		i += 1
	EndWhile
	Return out
EndFunction
