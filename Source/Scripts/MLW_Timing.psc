Scriptname MLW_Timing Hidden
{Mantella Living World - Integration Hub: speed testing switches and stage times, off by default (the Hub's Settings
page, "Speed testing", writes StorageUtilData/MantellaLivingWorld/perf.json: timing, prepare).

With timing on, one row per stage goes to Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv:
talk,real_time,who,stage,detail. real_time is Utility.GetCurrentRealTime (seconds since the game started); talk is
StorageUtil's MLW_TimingTalk, raised at the talk key (or at the first join of a talk started another way) and written
to timing_talk.json, where the Hub's side reads it for its own rows (timing_backend.csv). Other modules write the same
rows themselves when StorageUtil's MLW_TimingOn is 1 (no dependency on this script). Global functions only.}

string Function Perf() global
	Return "MantellaLivingWorld/perf.json"
EndFunction

string Function GameFile() global
	Return "Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv"
EndFunction

; Reads perf.json again (the Hub's side rewrites it while the game runs) into StorageUtil: MLW_TimingOn, MLW_PrepareOn.
Function ReadSettings() global
	JsonUtil.Unload(Perf(), false, false)
	StorageUtil.SetIntValue(None, "MLW_TimingOn", JsonUtil.GetIntValue(Perf(), "timing", 0))
	StorageUtil.SetIntValue(None, "MLW_PrepareOn", JsonUtil.GetIntValue(Perf(), "prepare", 0))
EndFunction

bool Function On() global
	Return StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1
EndFunction

bool Function PrepareOn() global
	Return StorageUtil.GetIntValue(None, "MLW_PrepareOn", 0) == 1
EndFunction

Function Mark(string asWho, string asStage, string asDetail = "") global
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1
		MiscUtil.WriteToFile(GameFile(), StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + "," + asWho + "," + asStage + "," + asDetail + "\n", true, false)
	EndIf
EndFunction

; A new talk number, for the talk key or the first join of a talk started another way.
Function NewTalk(string asHow) global
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) != 1
		Return
	EndIf
	int talk = StorageUtil.AdjustIntValue(None, "MLW_TimingTalk", 1)
	StorageUtil.SetFloatValue(None, "MLW_TimingTalkAt", Utility.GetCurrentRealTime())
	JsonUtil.SetIntValue("MantellaLivingWorld/timing_talk.json", "talk", talk)
	JsonUtil.Save("MantellaLivingWorld/timing_talk.json")
	Mark("hub", asHow)
EndFunction
