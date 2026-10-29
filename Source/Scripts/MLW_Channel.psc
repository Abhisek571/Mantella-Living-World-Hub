Scriptname MLW_Channel extends Quest
{The file channel: what Mantella's side needs to know about the NPCs in a conversation, written as PapyrusUtil
JSON under SKSE/Plugins/StorageUtilData/MantellaLivingWorld/ for the Living World extension in Mantella.

npc/<base id>.json: name, ref_id, close (see CloseValue), follower, guard, rated
(OStim Expansion positions). conversation.json: the player's name and the base ids of everyone in the current conversation. On its own quest:
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
	StorageUtil.SetFloatValue(npc, "MLW_SpeakerAdded", Utility.GetCurrentRealTime())
	StorageUtil.FormListAdd(self, "MLW_Speakers", npc, false)
	WriteSpeakers()
EndEvent

Event OnNpcRemoved(Form akActor)
	StorageUtil.FormListRemove(self, "MLW_Speakers", akActor, true)
	WriteSpeakers()
EndEvent

Event OnEnded()
	StorageUtil.FormListClear(self, "MLW_Speakers")
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
	JsonUtil.Save(CONVERSATION)
EndFunction

Function WriteNpc(Actor akNpc, string asId)
	string path = DIR + "npc/" + asId + ".json"
	JsonUtil.SetStringValue(path, "name", akNpc.GetDisplayName())
	JsonUtil.SetStringValue(path, "ref_id", Hex(akNpc.GetFormID()))
	JsonUtil.SetIntValue(path, "close", CloseValue(akNpc))
	JsonUtil.SetIntValue(path, "follower", IsFollower(akNpc) as int)
	JsonUtil.SetIntValue(path, "guard", akNpc.IsGuard() as int)
	JsonUtil.SetIntValue(path, "rated", StorageUtil.GetIntValue(akNpc, "MAE_PosesRated", 0))
	JsonUtil.Save(path)
EndFunction

; Arousal's standing when it has one (1 close, 2 an open group); otherwise close for a vanilla friend or better, a
; teammate, or someone Relationships marks close (MRB_Close: engaged or married). Arousal sets its value in its own
; NPC_Added handler and then sends MLW_RefreshNpc, so a value left from the previous talk is replaced.
int Function CloseValue(Actor akNpc)
	int standing = StorageUtil.GetIntValue(akNpc, "MLW_IsClose", 0)
	If standing > 0
		Return standing
	EndIf
	If akNpc.GetRelationshipRank(PlayerRef) >= 1 || akNpc.IsPlayerTeammate() || StorageUtil.GetIntValue(akNpc, "MRB_Close", 0) > 0
		Return 1
	EndIf
	Return 0
EndFunction

; In the party, or a vanilla potential follower (CurrentFollowerFaction / PotentialFollowerFaction in Skyrim.esm).
bool Function IsFollower(Actor akNpc)
	If akNpc.IsPlayerTeammate()
		Return true
	EndIf
	Faction current = Game.GetFormFromFile(0x05C84E, "Skyrim.esm") as Faction
	Faction potential = Game.GetFormFromFile(0x05C84D, "Skyrim.esm") as Faction
	Return (current && akNpc.GetFactionRank(current) >= 0) || (potential && akNpc.IsInFaction(potential))
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
