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

Event OnConfigOpen()
	CheckModules()
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
