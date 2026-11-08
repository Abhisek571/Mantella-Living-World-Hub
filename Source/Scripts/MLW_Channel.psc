Scriptname MLW_Channel extends Quest
{The file channel: what Mantella's side needs to know about the NPCs in a conversation, written as PapyrusUtil
JSON under SKSE/Plugins/StorageUtilData/MantellaLivingWorld/ for the Living World extension in Mantella.

npc/<base id>.json: name, ref_id, close (see CloseValue), intimate (see IntimateValue), minor (1 for a child),
follower, guard, rated (OStim Expansion positions), and for the world note and the basic bio: hold (where they belong, see NpcHold),
location (where they are now), here_hold (the hold they are in now), race, sex, class, work (their vanilla job faction) and groups (the guilds and sides
World's quest outcomes are told to). conversation.json: the player's name and the base ids of everyone in the current conversation. On its own quest:
SKSE keeps one mod event registration per object.

Modules send "MLW_RefreshNpc" (one Form) after they change what the file holds (Arousal after it works out how
close the NPC is, Relationships after an engagement, Followers after a join or leave), so the file is rewritten
during the talk instead of keeping what it held when the NPC joined.}

Actor Property PlayerRef Auto

string Property DIR = "MantellaLivingWorld/" AutoReadOnly
string Property CONVERSATION = "MantellaLivingWorld/conversation.json" AutoReadOnly

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
EndFunction

Event OnRefreshNpc(Form akActor)
	Actor npc = akActor as Actor
	If npc && npc != PlayerRef
		WriteNpc(npc, BaseId(npc))
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
	Register()  ; saves that started this quest before an event was added never ran OnInit again
	WriteNpc(npc, BaseId(npc))
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
EndEvent

Event OnNpcRemoved(Form akActor)
	StorageUtil.FormListRemove(self, "MLW_Speakers", akActor, true)
	WriteSpeakers()
EndEvent

; The Ended event of a talk can arrive after the next talk has already added its first NPC (a new talk started within
; seconds): keep whoever is in Mantella's running conversation, so that talk keeps its speakers and gates.
Event OnEnded()
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
	JsonUtil.Save(CONVERSATION)
EndFunction

Function WriteNpc(Actor akNpc, string asId)
	string path = DIR + "npc/" + asId + ".json"
	JsonUtil.SetStringValue(path, "name", akNpc.GetDisplayName())
	JsonUtil.SetStringValue(path, "ref_id", Hex(akNpc.GetFormID()))
	JsonUtil.SetIntValue(path, "close", CloseValue(akNpc))
	JsonUtil.SetIntValue(path, "intimate", IntimateValue(akNpc))
	JsonUtil.SetIntValue(path, "minor", IsMinor(akNpc) as int)
	JsonUtil.SetIntValue(path, "follower", IsFollower(akNpc) as int)
	JsonUtil.SetIntValue(path, "guard", akNpc.IsGuard() as int)
	JsonUtil.SetIntValue(path, "rated", StorageUtil.GetIntValue(akNpc, "MAE_PosesRated", 0))
	WriteWho(akNpc, path)
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
int Function CloseValue(Actor akNpc)
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
	Return 0
EndFunction

; 1 when the player may be intimate with this NPC (the gate of the OStim and Arousal adult actions): a vanilla lover
; (rank 4), dating or closer in Relationships, an open group in Arousal, or the player's own "Allow intimacy" choice
; on the Living World hotkey (MLW_Intimate). A friend, a follower or a forward temperament is close, never intimate.
int Function IntimateValue(Actor akNpc)
	If IsMinor(akNpc)
		Return 0
	EndIf
	If akNpc.GetRelationshipRank(PlayerRef) >= 4 || RelationshipsClose(akNpc) > 0 || ArousalStanding(akNpc) == 2
		Return 1
	EndIf
	If StorageUtil.GetIntValue(akNpc, "MLW_Intimate", 0) == 1
		Return 1
	EndIf
	Return 0
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
