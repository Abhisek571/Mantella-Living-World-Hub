Scriptname MLW_Pace Hidden
{Mantella Living World - Integration Hub: pacing for lines nobody asked for (banter, reactions, an NPC walking up to
talk). Every module asks TryClaim(source, cooldown) before it speaks; at most one claim wins, the rest are dropped,
never queued. A claim fails while the hub is quiet, while a Mantella conversation runs, within GAP seconds of the last
claim of any source, within the source's own cooldown, or when HOURLY claims were made in the last hour.

Times are real seconds since the game was started; a time from an earlier launch (larger than now) counts as stale.}

float Function GAP() global
	Return 10.0
EndFunction

; Most ambient lines per hour, all sources together (MLW_PaceHourly, World page of the MCM).
int Function HOURLY() global
	GlobalVariable g = Game.GetFormFromFile(0x00080A, "Mantella Living World - Integration Hub.esp") as GlobalVariable
	int n = 6
	If g
		n = g.GetValueInt()
	EndIf
	If n < 1
		Return 1
	EndIf
	Return n
EndFunction

bool Function TryClaim(string asSource, float afCooldown) global
	float now = Utility.GetCurrentRealTime()
	string why = Blocked(asSource, afCooldown, now)
	If why != ""
		StorageUtil.SetStringValue(None, "MLW_PaceLastRefusal", asSource + ": " + why)
		Return false
	EndIf
	StorageUtil.SetFloatValue(None, "MLW_PaceAt_" + asSource, now)
	StorageUtil.SetFloatValue(None, "MLW_PaceLastAt", now)
	StorageUtil.SetStringValue(None, "MLW_PaceLastSource", asSource)
	StorageUtil.FloatListAdd(None, "MLW_PaceTimes", now)
	Return true
EndFunction

; "" when a claim may go ahead, otherwise the reason (kept for the report).
string Function Blocked(string asSource, float afCooldown, float afNow) global
	MLW_Hub hub = Game.GetFormFromFile(0x000820, "Mantella Living World - Integration Hub.esp") as MLW_Hub
	If hub && hub.IsQuiet()
		Return "hub quiet"
	EndIf
	Quest talk = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as Quest
	If talk && talk.IsRunning()
		Return "Mantella conversation running"
	EndIf
	float last = StorageUtil.GetFloatValue(None, "MLW_PaceLastAt", -1.0)
	If last >= 0.0 && last <= afNow && afNow - last < GAP()
		Return "another line just now"
	EndIf
	float mine = StorageUtil.GetFloatValue(None, "MLW_PaceAt_" + asSource, -1.0)
	If mine >= 0.0 && mine <= afNow && afNow - mine < afCooldown
		Return "cooldown"
	EndIf
	; Forget claims older than an hour or from an earlier launch.
	int i = StorageUtil.FloatListCount(None, "MLW_PaceTimes")
	While i > 0
		i -= 1
		float t = StorageUtil.FloatListGet(None, "MLW_PaceTimes", i)
		If t > afNow || afNow - t > 3600.0
			StorageUtil.FloatListRemoveAt(None, "MLW_PaceTimes", i)
		EndIf
	EndWhile
	If StorageUtil.FloatListCount(None, "MLW_PaceTimes") >= HOURLY()
		Return "hourly limit"
	EndIf
	Return ""
EndFunction

; Clears every claim (testing, and the MCM's reset button).
Function Reset() global
	StorageUtil.FloatListClear(None, "MLW_PaceTimes")
	StorageUtil.UnsetFloatValue(None, "MLW_PaceLastAt")
	StorageUtil.UnsetStringValue(None, "MLW_PaceLastSource")
	StorageUtil.UnsetStringValue(None, "MLW_PaceLastRefusal")
	string[] sources = new string[2]
	sources[0] = "banter"
	sources[1] = "initiative"
	int i = 0
	While i < sources.Length
		StorageUtil.UnsetFloatValue(None, "MLW_PaceAt_" + sources[i])
		i += 1
	EndWhile
EndFunction

; One line for the troubleshooting report.
string Function ReportText() global
	float now = Utility.GetCurrentRealTime()
	float last = StorageUtil.GetFloatValue(None, "MLW_PaceLastAt", -1.0)
	string s = StorageUtil.FloatListCount(None, "MLW_PaceTimes") + " of " + HOURLY() + " lines this hour"
	If last >= 0.0 && last <= now
		s += ", last " + StorageUtil.GetStringValue(None, "MLW_PaceLastSource") + " " + ((now - last) as int) + " s ago"
	EndIf
	string refused = StorageUtil.GetStringValue(None, "MLW_PaceLastRefusal")
	If refused != ""
		s += ", last refused: " + refused
	EndIf
	Return s
EndFunction
