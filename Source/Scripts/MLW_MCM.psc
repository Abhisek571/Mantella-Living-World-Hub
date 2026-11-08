Scriptname MLW_MCM extends MCM_ConfigBase
{The hub's MCM Helper menu. Buttons call the functions here.}

; Module status page: read-only checks, filled in every time the menu opens.
bool Property Never = false Auto
bool Property HasHub = true Auto
bool Property HasOStimExpansion Auto
bool Property HasArousal Auto
bool Property HasRelationships Auto
bool Property HasFollowers Auto
bool Property HasWorld Auto
bool Property HasMantella Auto
bool Property HasOStim Auto
bool Property HasOSL Auto
bool Property HasMARAS Auto
bool Property HasLedger Auto
bool Property HasRelationsFinder Auto
bool Property HasNFF Auto

; Cheats page (testing): off unless switched on in Overview. Acts on the NPC under the crosshair when the menu opened,
; else the last NPC who joined a Mantella talk. Relationship and teammate are set here; the modules apply the rest
; from the "MLW_Cheat" mod event (Form npc, string what, float value), so no module depends on another.
bool Property CheatsOn = false Auto
int Property RelChoice = 0 Auto
int Property MarasChoice = 0 Auto
float Property MarasAffection = 50.0 Auto
float Property ArousalValue = 0.0 Auto
Actor target

Event OnConfigOpen()
	CheckModules()
	If CheatsOn
		PickTarget()
	EndIf
EndEvent

Event OnPageSelect(string a_page)
	CheckModules()
EndEvent

Function CheckModules()
	Never = false
	HasHub = true
	HasOStimExpansion = Loaded("Mantella Living World - OStim Expansion.esp")
	HasArousal = Loaded("Mantella Living World - Arousal.esp")
	HasRelationships = Loaded("Mantella Living World - Relationships.esp")
	HasFollowers = Loaded("Mantella Living World - Followers.esp")
	HasWorld = Loaded("Mantella Living World - World.esp")
	HasMantella = Loaded("Mantella.esp")
	HasOStim = Loaded("OStim.esp")
	HasOSL = Loaded("OSLAroused.esp")
	HasMARAS = Loaded("TT_MARAS.esp")
	HasLedger = SKSE.GetPluginVersion("LoversLedger") > 0 ; an SKSE plugin, no .esp
	HasRelationsFinder = SKSE.GetPluginVersion("RelationsFinder") >= 0 ; an SKSE plugin, no .esp
	HasNFF = Loaded("nwsFollowerFramework.esp")
EndFunction

bool Function Loaded(string asPlugin)
	Return Game.GetModByName(asPlugin) != 255 || Game.GetLightModByName(asPlugin) != 65535
EndFunction

Function WriteReport()
	MLW_Hub hub = Game.GetFormFromFile(0x000820, "Mantella Living World - Integration Hub.esp") as MLW_Hub
	If hub
		hub.WriteReport()
	EndIf
EndFunction

Function ResetPace()
	MLW_Pace.Reset()
	Debug.MessageBox("Pacing reset: cooldowns and this hour's count are cleared.")
EndFunction

; ---------------------------------------------------------------------------
; Cheats (testing)
; ---------------------------------------------------------------------------

; Picked fresh every time the menu opens: the NPC under the crosshair, else the last NPC the player talked to.
Function PickTarget()
	target = None
	Actor aimed = Game.GetCurrentCrosshairRef() as Actor
	If aimed && aimed != Game.GetPlayer() && !aimed.IsDead()
		target = aimed
	Else
		Actor last = StorageUtil.GetFormValue(None, "MLW_LastNpc") as Actor
		If last && !last.IsDead() && !IsChildActor(last)
			target = last
		EndIf
	EndIf
EndFunction

bool Function IsChildActor(Actor akActor)
	Return akActor.IsChild() || StringUtil.Find(MiscUtil.GetRaceEditorID(akActor.GetRace()), "Child") >= 0
EndFunction

; The target, or None with a message saying why there is none.
Actor Function Target()
	If !target
		Debug.MessageBox("No target. Aim at an NPC (or talk to one), then open this menu again.")
		Return None
	EndIf
	If IsChildActor(target)
		Debug.MessageBox("Cheats do not work on children.")
		Return None
	EndIf
	Return target
EndFunction

Function ShowTarget()
	If target
		Debug.MessageBox("Cheats act on: " + target.GetDisplayName() + "\n\nThe NPC under your crosshair when you opened this menu, else the last NPC you talked to. To change it, close the menu, aim at someone and open it again.")
	Else
		Target()
	EndIf
EndFunction

; Stranger, Friend, Lover, Follower: vanilla relationship rank 0, 1, 4, and 1 plus teammate.
Function SetRelationship(int aiChoice)
	Actor npc = Target()
	If !npc
		Return
	EndIf
	Remember(npc)
	Actor player = Game.GetPlayer()
	int rank = 0
	If aiChoice == 1 || aiChoice == 3
		rank = 1
	ElseIf aiChoice == 2
		rank = 4
	EndIf
	npc.SetRelationshipRank(player, rank)
	player.SetRelationshipRank(npc, rank)
	npc.SetPlayerTeammate(aiChoice == 3)
	RememberSet(npc)
	StorageUtil.UnsetIntValue(npc, "MLW_IsClose")  ; Arousal works its standing out again on the refresh
	Refresh(npc)
	Debug.Notification(npc.GetDisplayName() + ": " + RelName(aiChoice))
EndFunction

; Candidate, Engaged, Married (Relationships applies it)
Function SetMaras(int aiChoice)
	Actor npc = Target()
	If npc
		Cheat(npc, "maras_status", aiChoice as float)
	EndIf
EndFunction

Function SetMarasAffection(float afValue)
	Actor npc = Target()
	If npc
		Cheat(npc, "maras_affection", afValue)
	EndIf
EndFunction

Function SetArousal(float afValue)
	Actor npc = Target()
	If npc
		Cheat(npc, "arousal", afValue)
	EndIf
EndFunction

; What the gated actions see for the target right now (the values the Hub writes into their file, plus each module's own).
Function ShowCanDo()
	Actor npc = Target()
	If !npc
		Return
	EndIf
	MLW_Channel channel = Game.GetFormFromFile(0x000823, "Mantella Living World - Integration Hub.esp") as MLW_Channel
	string path = "MantellaLivingWorld/npc/" + channel.BaseId(npc) + ".json"
	JsonUtil.Unload(path, false)  ; other modules write this file too
	int close = channel.CloseValue(npc)
	int intimate = channel.IntimateValue(npc)
	bool follower = channel.IsFollower(npc)
	bool guard = npc.IsGuard()
	string text = npc.GetDisplayName() + "\n\n"
	text += "Close: " + YesNo(close > 0) + "  (rank " + npc.GetRelationshipRank(Game.GetPlayer()) + ", follower " + YesNo(follower) + ")\n"
	text += "Intimate actions (OStim, Arousal): " + YesNo(intimate > 0) + "\n"
	If HasOStimExpansion
		text += "Affection actions here: " + YesNo(close > 0 && JsonUtil.GetIntValue(path, "affection", 0) == 1) + "\n"
	EndIf
	If HasFollowers
		text += "Party orders: " + YesNo(follower) + "   Join party: " + YesNo(!guard) + "\n"
	EndIf
	If HasRelationships && HasMARAS
		string[] marasNames = new string[5]
		marasNames[0] = "none"
		marasNames[1] = "can accept a proposal"
		marasNames[2] = "engaged: can break it off"
		marasNames[3] = "married: can divorce"
		marasNames[4] = "married, in a crisis"
		int maras = JsonUtil.GetIntValue(path, "maras", 0)
		If maras >= 0 && maras <= 4
			text += "M.A.R.A.S: " + marasNames[maras] + "\n"
		EndIf
	EndIf
	If HasWorld
		text += "Crime actions (guards only): " + YesNo(guard) + "\n"
	EndIf
	text += "\nUpdates when the NPC next joins a talk or a cheat refreshes them."
	Debug.MessageBox(text)
EndFunction

; Puts back the relationship rank and teammate state from before the first cheat, but only a part that still holds
; what the cheat set: a marriage, a hire or a quarrel since then is real play and is left as it is. The modules undo
; their own parts.
Function ResetTarget()
	Actor npc = Target()
	If !npc
		Return
	EndIf
	Actor player = Game.GetPlayer()
	string back = ""
	string kept = ""
	If StorageUtil.HasIntValue(npc, "MLW_CheatRank")
		If npc.GetRelationshipRank(player) == StorageUtil.GetIntValue(npc, "MLW_CheatRankSet", -100)
			int rank = StorageUtil.GetIntValue(npc, "MLW_CheatRank")
			npc.SetRelationshipRank(player, rank)
			player.SetRelationshipRank(npc, rank)
			back += "\n- relationship"
		Else
			kept += "\n- relationship"
		EndIf
		If (npc.IsPlayerTeammate() as int) == StorageUtil.GetIntValue(npc, "MLW_CheatTeammateSet", -100)
			npc.SetPlayerTeammate(StorageUtil.GetIntValue(npc, "MLW_CheatTeammate") == 1)
			back += "\n- follower flag"
		Else
			kept += "\n- follower flag"
		EndIf
		StorageUtil.UnsetIntValue(npc, "MLW_CheatRank")
		StorageUtil.UnsetIntValue(npc, "MLW_CheatTeammate")
		StorageUtil.UnsetIntValue(npc, "MLW_CheatRankSet")
		StorageUtil.UnsetIntValue(npc, "MLW_CheatTeammateSet")
		StorageUtil.UnsetIntValue(npc, "MLW_IsClose")
	EndIf
	Cheat(npc, "reset", 0.0)
	Refresh(npc)
	string text = npc.GetDisplayName() + ": the modules put back what their cheats changed (a M.A.R.A.S status change stays)."
	If back != ""
		text += "\n\nPut back:" + back
	EndIf
	If kept != ""
		text += "\n\nChanged since the cheat, left as it is:" + kept
	EndIf
	Debug.MessageBox(text)
EndFunction

Function Remember(Actor akNpc)
	If !StorageUtil.HasIntValue(akNpc, "MLW_CheatRank")
		StorageUtil.SetIntValue(akNpc, "MLW_CheatRank", akNpc.GetRelationshipRank(Game.GetPlayer()))
		StorageUtil.SetIntValue(akNpc, "MLW_CheatTeammate", akNpc.IsPlayerTeammate() as int)
	EndIf
EndFunction

; What the latest cheat set, so Reset can tell whether the game changed it since.
Function RememberSet(Actor akNpc)
	StorageUtil.SetIntValue(akNpc, "MLW_CheatRankSet", akNpc.GetRelationshipRank(Game.GetPlayer()))
	StorageUtil.SetIntValue(akNpc, "MLW_CheatTeammateSet", akNpc.IsPlayerTeammate() as int)
EndFunction

; Every cheat names its target, so a wrong pick shows at once.
Function Cheat(Actor akNpc, string asWhat, float afValue)
	If asWhat != "reset"
		Debug.Notification(akNpc.GetDisplayName() + ": " + asWhat + " " + (afValue as int))
	EndIf
	int handle = ModEvent.Create("MLW_Cheat")
	If handle
		ModEvent.PushForm(handle, akNpc)
		ModEvent.PushString(handle, asWhat)
		ModEvent.PushFloat(handle, afValue)
		ModEvent.Send(handle)
	EndIf
EndFunction

Function Refresh(Actor akNpc)
	int handle = ModEvent.Create("MLW_RefreshNpc")
	If handle
		ModEvent.PushForm(handle, akNpc)
		ModEvent.Send(handle)
	EndIf
EndFunction

string Function RelName(int aiChoice)
	If aiChoice == 1
		Return "Friend"
	ElseIf aiChoice == 2
		Return "Lover"
	ElseIf aiChoice == 3
		Return "Follower"
	EndIf
	Return "Stranger"
EndFunction

string Function YesNo(bool abValue)
	If abValue
		Return "yes"
	EndIf
	Return "no"
EndFunction
