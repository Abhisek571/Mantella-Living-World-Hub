Scriptname MLW_Hub extends Quest
{Mantella Living World - Integration Hub: services the modules share.

Quiet outfits: Mantella reports every item an NPC or the player equips, unequips, picks up or drops. OStim scenes and
loading screens (outfits re-applied, Tailor outfit changes) produce dozens of these at once, which floods the
conversation. Any module asks for quiet with Quiet(reason) and ends it with Unquiet(reason, delay); Mantella's own
switches are saved when the first reason starts and put back when the last one ends, so modules never fight over them.
The hub itself keeps quiet for a few seconds after every loading screen.

Modules reach it with: Game.GetFormFromFile(0x000820, "Mantella Living World - Integration Hub.esp") as MLW_Hub}

Actor Property PlayerRef Auto
; 1 = quiet after loading screens.
GlobalVariable Property MLW_QuietLoads Auto
; Seconds of quiet after a loading screen or a module's scene end.
GlobalVariable Property MLW_QuietSeconds Auto
; 1 = modules write what they do to the debug log.
GlobalVariable Property MLW_DebugLog Auto

string Property KEY_REASONS = "MLW_QuietReasons" AutoReadOnly
string Property KEY_UNTIL = "MLW_QuietUntil" AutoReadOnly
string Property KEY_SAVED = "MLW_SavedTracking" AutoReadOnly
string Property REASON_LOAD = "load" AutoReadOnly
string Property VERSION = "1.0.0" AutoReadOnly
string Property LOG_FILE = "Data/SKSE/Plugins/MantellaLivingWorld/debug.log" AutoReadOnly
string Property REPORT_FILE = "Data/SKSE/Plugins/MantellaLivingWorld/report.txt" AutoReadOnly
string Property KEY_LOG = "MLW_LogLines" AutoReadOnly
string Property KEY_REPORT = "MLW_ReportLines" AutoReadOnly

Event OnInit()
	RegisterForMenu("Loading Menu")
EndEvent

Event OnMenuOpen(string asMenuName)
	If MLW_QuietLoads.GetValueInt() == 1
		Quiet(REASON_LOAD)
	EndIf
EndEvent

Event OnMenuClose(string asMenuName)
	Unquiet(REASON_LOAD, MLW_QuietSeconds.GetValue())
EndEvent

; ---------------------------------------------------------------------------
; Quiet outfits
; ---------------------------------------------------------------------------

; Starts (or renews) quiet for asReason; a pending delayed end for it is cancelled.
Function Quiet(string asReason)
	int i = StorageUtil.StringListFind(None, KEY_REASONS, asReason)
	If i < 0
		StorageUtil.StringListAdd(None, KEY_REASONS, asReason)
		StorageUtil.FloatListAdd(None, KEY_UNTIL, 0.0)
		If StorageUtil.StringListCount(None, KEY_REASONS) == 1
			MuteMantella()
		EndIf
		Log("hub", "quiet on: " + asReason)
	Else
		StorageUtil.FloatListSet(None, KEY_UNTIL, i, 0.0)
	EndIf
EndFunction

; Ends quiet for asReason, now or afDelay real seconds from now (the redress after a scene, outfits after a load).
Function Unquiet(string asReason, float afDelay = 0.0)
	int i = StorageUtil.StringListFind(None, KEY_REASONS, asReason)
	If i < 0
		Return
	EndIf
	If afDelay > 0.0
		StorageUtil.FloatListSet(None, KEY_UNTIL, i, Utility.GetCurrentRealTime() + afDelay)
		RegisterForSingleUpdate(afDelay)
	Else
		DropReason(i)
	EndIf
EndFunction

bool Function IsQuiet()
	Return StorageUtil.StringListCount(None, KEY_REASONS) > 0
EndFunction

Event OnUpdate()
	float now = Utility.GetCurrentRealTime()
	float nextAt = 0.0
	int i = StorageUtil.StringListCount(None, KEY_REASONS) - 1
	While i >= 0
		float untilTime = StorageUtil.FloatListGet(None, KEY_UNTIL, i)
		; Real time restarts at 0 on a new launch, so a time far in the future is stale too.
		If untilTime > 0.0 && (untilTime <= now || untilTime - now > 600.0)
			DropReason(i)
		ElseIf untilTime > 0.0 && (nextAt == 0.0 || untilTime < nextAt)
			nextAt = untilTime
		EndIf
		i -= 1
	EndWhile
	If nextAt > 0.0
		RegisterForSingleUpdate(nextAt - now + 0.1)
	EndIf
EndEvent

Function DropReason(int aiIndex)
	Log("hub", "quiet off: " + StorageUtil.StringListGet(None, KEY_REASONS, aiIndex))
	StorageUtil.StringListRemoveAt(None, KEY_REASONS, aiIndex)
	StorageUtil.FloatListRemoveAt(None, KEY_UNTIL, aiIndex)
	If StorageUtil.StringListCount(None, KEY_REASONS) == 0
		RestoreMantella()
	EndIf
EndFunction

; Saves and switches off Mantella's equip/unequip and item added/removed tracking, for the player and NPCs.
Function MuteMantella()
	MantellaRepository repo = Game.GetFormFromFile(0x000D62, "Mantella.esp") as MantellaRepository
	If !repo || StorageUtil.IntListCount(None, KEY_SAVED) == 8
		Return
	EndIf
	StorageUtil.IntListClear(None, KEY_SAVED)
	StorageUtil.IntListAdd(None, KEY_SAVED, repo.playerTrackingOnObjectEquipped as int)
	StorageUtil.IntListAdd(None, KEY_SAVED, repo.playerTrackingOnObjectUnequipped as int)
	StorageUtil.IntListAdd(None, KEY_SAVED, repo.playerTrackingOnItemAdded as int)
	StorageUtil.IntListAdd(None, KEY_SAVED, repo.playerTrackingOnItemRemoved as int)
	StorageUtil.IntListAdd(None, KEY_SAVED, repo.targetTrackingOnObjectEquipped as int)
	StorageUtil.IntListAdd(None, KEY_SAVED, repo.targetTrackingOnObjectUnequipped as int)
	StorageUtil.IntListAdd(None, KEY_SAVED, repo.targetTrackingItemAdded as int)
	StorageUtil.IntListAdd(None, KEY_SAVED, repo.targetTrackingItemRemoved as int)
	repo.playerTrackingOnObjectEquipped = false
	repo.playerTrackingOnObjectUnequipped = false
	repo.playerTrackingOnItemAdded = false
	repo.playerTrackingOnItemRemoved = false
	repo.targetTrackingOnObjectEquipped = false
	repo.targetTrackingOnObjectUnequipped = false
	repo.targetTrackingItemAdded = false
	repo.targetTrackingItemRemoved = false
EndFunction

Function RestoreMantella()
	MantellaRepository repo = Game.GetFormFromFile(0x000D62, "Mantella.esp") as MantellaRepository
	If !repo || StorageUtil.IntListCount(None, KEY_SAVED) != 8
		Return
	EndIf
	repo.playerTrackingOnObjectEquipped = StorageUtil.IntListGet(None, KEY_SAVED, 0) == 1
	repo.playerTrackingOnObjectUnequipped = StorageUtil.IntListGet(None, KEY_SAVED, 1) == 1
	repo.playerTrackingOnItemAdded = StorageUtil.IntListGet(None, KEY_SAVED, 2) == 1
	repo.playerTrackingOnItemRemoved = StorageUtil.IntListGet(None, KEY_SAVED, 3) == 1
	repo.targetTrackingOnObjectEquipped = StorageUtil.IntListGet(None, KEY_SAVED, 4) == 1
	repo.targetTrackingOnObjectUnequipped = StorageUtil.IntListGet(None, KEY_SAVED, 5) == 1
	repo.targetTrackingItemAdded = StorageUtil.IntListGet(None, KEY_SAVED, 6) == 1
	repo.targetTrackingItemRemoved = StorageUtil.IntListGet(None, KEY_SAVED, 7) == 1
	StorageUtil.IntListClear(None, KEY_SAVED)
EndFunction

; ---------------------------------------------------------------------------
; Troubleshooting: a debug log modules write to, and a report for bug reports
; ---------------------------------------------------------------------------

; Any module: Hub.Log("ostim", "scene started"). Written only while the debug log is on; the last 50 lines also go
; into the report.
Function Log(string asModule, string asText)
	If !MLW_DebugLog || MLW_DebugLog.GetValueInt() != 1
		Return
	EndIf
	string line = "[" + Utility.GetCurrentGameTime() + "] " + asModule + ": " + asText
	MiscUtil.WriteToFile(LOG_FILE, line + "\n", true, false)
	StorageUtil.StringListAdd(None, KEY_LOG, line)
	While StorageUtil.StringListCount(None, KEY_LOG) > 50
		StorageUtil.StringListRemoveAt(None, KEY_LOG, 0)
	EndWhile
EndFunction

; Modules answer the "MLW_ReportRequest" event with their own lines.
Function ReportAdd(string asModule, string asText)
	StorageUtil.StringListAdd(None, KEY_REPORT, asModule + ": " + asText)
EndFunction

; Writes SKSE\Plugins\MantellaLivingWorld\report.txt: versions, what is installed, every setting, the quiet state,
; Mantella's conversation, what each module reports, and the last debug lines. No player name, no paths.
Function WriteReport()
	StorageUtil.StringListClear(None, KEY_REPORT)
	int request = ModEvent.Create("MLW_ReportRequest")
	If request
		ModEvent.Send(request)
	EndIf
	Utility.WaitMenuMode(2.0)
	string r = "Mantella Living World report\n"
	r += "Hub " + VERSION + ", SKSE " + SKSE.GetVersion() + "." + SKSE.GetVersionMinor() + "." + SKSE.GetVersionBeta() + ", PapyrusUtil " + PapyrusUtil.GetVersion() + "\n\n"
	r += "[Modules]\n" + Has("Mantella Living World - OStim Expansion.esp") + Has("Mantella Living World - Arousal.esp") + Has("Mantella Living World - Relationships.esp") + Has("Mantella Living World - Followers.esp") + Has("Mantella Living World - World.esp")
	r += "\n[Mods]\n" + Has("Mantella.esp") + Has("OStim.esp") + Has("OSLAroused.esp") + Has("TT_MARAS.esp") + Has("nwsFollowerFramework.esp") + Has("MCMHelper.esp") + Has("SkyUI_SE.esp")
	r += "\n[Settings]\n"
	string[] names = new string[11]
	names[0] = "Quiet after loading screens"
	names[1] = "Quiet for (seconds)"
	names[2] = "Default temperament (0 Auto, 1 Reserved, 2 Bold, 3 Forward)"
	names[3] = "Auto judges lust from (0 appetite rating, 1 OSL values)"
	names[4] = "Never force-start a scene"
	names[5] = "Hotkey (DirectX code)"
	names[6] = "Setup reminder"
	names[7] = "Setup done"
	names[8] = "Quiet during scenes"
	names[9] = "Debug log"
	names[10] = "Ambient lines per hour"
	int id = 0
	While id < 11
		GlobalVariable g = Game.GetFormFromFile(0x800 + id, "Mantella Living World - Integration Hub.esp") as GlobalVariable
		If g
			r += "  " + names[id] + " = " + g.GetValue() + "\n"
		EndIf
		id += 1
	EndWhile
	r += "\n[Quiet outfits]\n  " + TestState() + "\n"
	r += "\n[Mantella conversation]\n  " + ConversationText() + "\n"
	r += "\n[Temperament]\n  " + TemperText() + "\n"
	r += "\n[Pacing]\n  " + MLW_Pace.ReportText() + "\n"
	r += "\n[Modules report]\n"
	int i = 0
	While i < StorageUtil.StringListCount(None, KEY_REPORT)
		r += "  " + StorageUtil.StringListGet(None, KEY_REPORT, i) + "\n"
		i += 1
	EndWhile
	r += "\n[Last debug lines]"
	If !MLW_DebugLog || MLW_DebugLog.GetValueInt() != 1
		r += " (debug log is off)"
	EndIf
	r += "\n"
	i = 0
	While i < StorageUtil.StringListCount(None, KEY_LOG)
		r += "  " + StorageUtil.StringListGet(None, KEY_LOG, i) + "\n"
		i += 1
	EndWhile
	r += "\nMantella's own log is Documents\\My Games\\Mantella\\logging.log. Attach it too.\n"
	MiscUtil.WriteToFile(REPORT_FILE, r, false, false)
	Debug.MessageBox("Report written to SKSE\\Plugins\\MantellaLivingWorld\\report.txt (with MO2: in the overwrite folder).\n\nAttach it to a bug report together with Mantella's logging.log.")
EndFunction

string Function Has(string asPlugin)
	If Game.GetModByName(asPlugin) != 255 || Game.GetLightModByName(asPlugin) != 65535
		Return "  " + asPlugin + ": yes\n"
	EndIf
	Return "  " + asPlugin + ": MISSING\n"
EndFunction

string Function ConversationText()
	MantellaConversation c = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	If !c
		Return "Mantella not found"
	ElseIf !c.IsRunning()
		Return "no conversation running"
	EndIf
	string s = "running with: "
	int i = 0
	While i < c.CountActorsInConversation()
		Actor a = c.GetActorInConversationByIndex(i)
		If a && a != PlayerRef
			s += a.GetDisplayName() + ", "
		EndIf
		i += 1
	EndWhile
	Return s
EndFunction

string Function TemperText()
	MLW_Setup setup = Game.GetFormFromFile(0x000821, "Mantella Living World - Integration Hub.esp") as MLW_Setup
	Actor target = Game.GetCurrentCrosshairRef() as Actor
	If !setup
		Return "setup quest missing"
	ElseIf !target || target == PlayerRef
		Return "nobody under the crosshair"
	EndIf
	Return target.GetDisplayName() + ": " + setup.TierName(setup.TierOf(target)) + ", override " + StorageUtil.GetIntValue(target, setup.KEY_OVERRIDE, 0)
EndFunction

; Testing: the switches and the active reasons as text.
string Function TestState()
	MantellaRepository r = Game.GetFormFromFile(0x000D62, "Mantella.esp") as MantellaRepository
	string s = "reasons="
	int i = 0
	While i < StorageUtil.StringListCount(None, KEY_REASONS)
		s += StorageUtil.StringListGet(None, KEY_REASONS, i) + "@" + StorageUtil.FloatListGet(None, KEY_UNTIL, i) + ","
		i += 1
	EndWhile
	If r
		s += " player " + (r.playerTrackingOnObjectEquipped as int) + (r.playerTrackingOnObjectUnequipped as int) + (r.playerTrackingOnItemAdded as int) + (r.playerTrackingOnItemRemoved as int)
		s += " npc " + (r.targetTrackingOnObjectEquipped as int) + (r.targetTrackingOnObjectUnequipped as int) + (r.targetTrackingItemAdded as int) + (r.targetTrackingItemRemoved as int)
	EndIf
	Return s
EndFunction
