Scriptname MLW_Setup extends Quest
{Temperament: how shy or forward NPCs are about intimacy (reserved, bold, forward), shared by every Living World
module. Aim at an NPC and press the hotkey to set hers (Auto, Reserved, Bold, Forward); press it with nobody aimed at
to run the setup. Once per game launch it reminds about a setup that was never run. Settings are in the hub's MCM.
The Arousal module decides Auto (its GetTier reads the overrides and defaults set here; asked through MLW_TierRequest).
Children never get a temperament.}

Actor Property PlayerRef Auto
; DirectX scan code of the hotkey (0 = off).
GlobalVariable Property MLW_Hotkey Auto
; 0 Auto, 1 Reserved, 2 Bold, 3 Forward: the temperament of NPCs without their own override.
GlobalVariable Property MLW_TemperDefault Auto
; What Auto judges lust from: 0 Mantella's appetite rating (OSL values until rated), 1 OSL Aroused values only.
GlobalVariable Property MLW_TemperSource Auto
GlobalVariable Property MLW_SetupReminder Auto
GlobalVariable Property MLW_SetupDone Auto

string Property KEY_OVERRIDE = "MLW_TemperOverride" AutoReadOnly
string Property AROUSAL_PLUGIN = "Mantella Living World - Arousal.esp" AutoReadOnly
; Written by the Arousal module on the actor: temperament + 1 (0 or unset = no answer).
string Property KEY_TIER = "MLW_Tier" AutoReadOnly

int registeredKey = 0
float lastRealTime = 0.0
float lastReminders = 0.0
bool reminding = false

Event OnInit()
	RegisterForMenu("Loading Menu")
	RegisterForSingleUpdate(5.0)
	; First start on an existing save: its loading screen is already over, so remind now.
	lastRealTime = Utility.GetCurrentRealTime()
	Utility.Wait(8.0)
	Reminders()
EndEvent

; Keeps the hotkey registration in step with the MCM setting.
Event OnUpdate()
	int wanted = MLW_Hotkey.GetValueInt()
	If wanted != registeredKey
		If registeredKey > 0
			UnregisterForKey(registeredKey)
		EndIf
		If wanted > 0
			RegisterForKey(wanted)
		EndIf
		registeredKey = wanted
	EndIf
	RegisterForSingleUpdate(10.0)
EndEvent

; A save finished loading. Real time starts again from zero when the game is relaunched, so reminders run
; once per launch rather than on every reload.
Event OnMenuClose(string asMenuName)
	float now = Utility.GetCurrentRealTime()
	bool newLaunch = now < lastRealTime || lastRealTime == 0.0
	lastRealTime = now
	If !newLaunch
		Return
	EndIf
	RegisterForSingleUpdate(1.0)
	Utility.Wait(3.0)
	Reminders()
EndEvent

Function Reminders()
	; The first start on an existing save can reach here from both OnInit and the loading screen, at the same moment:
	; the flag is set before any call that could let the other one run.
	If reminding
		Return
	EndIf
	reminding = true
	float now = Utility.GetCurrentRealTime()
	If lastReminders > 0.0 && now >= lastReminders && now - lastReminders < 60.0
		reminding = false
		Return
	EndIf
	lastReminders = now
	; Never over the main menu or a loading screen: wait until the player is in the world.
	int tries = 0
	While (Utility.IsInMenuMode() || !PlayerRef.Is3DLoaded()) && tries < 120
		Utility.WaitMenuMode(1.0)
		tries += 1
	EndWhile
	If MLW_SetupReminder.GetValueInt() == 1 && MLW_SetupDone.GetValueInt() != 1
		string pick = SkyMessage.Show("Mantella Living World: setup hasn't been run yet.\n\nIt sets everyone's default temperament (how shy or forward NPCs are). You can also run it later: press the Living World hotkey while aiming at nobody.", "Run setup now", "Later", "Don't remind me")
		If pick == "Run setup now"
			RunSetup()
		ElseIf pick == "Don't remind me"
			MLW_SetupReminder.SetValueInt(0)
		EndIf
	EndIf
	reminding = false
EndFunction

; ---------------------------------------------------------------------------
; Hotkey
; ---------------------------------------------------------------------------

Event OnKeyDown(int aiKeyCode)
	If aiKeyCode != registeredKey || Utility.IsInMenuMode() || UI.IsTextInputEnabled()
		Return
	EndIf
	Actor target = Game.GetCurrentCrosshairRef() as Actor
	If target && IsMinor(target)
		Return
	ElseIf target && target != PlayerRef && !target.IsDead()
		PickTemperament(target)
	Else
		RunSetup()
	EndIf
EndEvent

Function PickTemperament(Actor akActor)
	string name = akActor.GetDisplayName()
	int current = StorageUtil.GetIntValue(akActor, KEY_OVERRIDE, 0)
	string now = TierName(TierOf(akActor))
	If current == 0
		now += " (Auto)"
	Else
		now += " (set by you)"
	EndIf
	int pick = SkyMessage.Show("Temperament for " + name + "\nNow: " + now + "\n\nReserved never asks the player for sex, Bold asks at peak but accepts no, Forward is the most insistent. Auto works it out from her lust and closeness to you.", \
			"Auto", "Reserved (shy)", "Bold (asks)", "Forward (insistent)", "Cancel", getIndex = true) as int
	If pick >= 0 && pick <= 3
		StorageUtil.SetIntValue(akActor, KEY_OVERRIDE, pick)
		Debug.Notification(name + ": " + TierName(TierOf(akActor)))
	EndIf
EndFunction

; ---------------------------------------------------------------------------
; Setup
; ---------------------------------------------------------------------------

Function RunSetup()
	int def = SkyMessage.Show("Living World setup (1/2)\n\nDefault temperament for everyone without their own setting:", \
			"Auto (recommended)", "Reserved (shy)", "Bold (asks)", "Forward (insistent)", "Cancel", getIndex = true) as int
	If def < 0 || def > 3
		Return
	EndIf
	int source = SkyMessage.Show("Living World setup (2/2)\n\nWhen temperament is Auto, judge how lustful an NPC is from:", \
			"Mantella's appetite rating", "OSL Aroused values only", "Cancel", getIndex = true) as int
	If source < 0 || source > 1
		Return
	EndIf
	MLW_TemperDefault.SetValueInt(def)
	MLW_TemperSource.SetValueInt(source)
	MLW_SetupDone.SetValueInt(1)
	SkyMessage.Show(Results(), "OK")
EndFunction

; Followers nearby and every NPC with a Mantella appetite rating, with the temperament each now has.
string Function Results()
	Form[] rated = StorageUtil.debug_AllIntObjs()
	Actor[] nearby = MiscUtil.ScanCellNPCs(PlayerRef, 3000.0)
	Faction followers = Game.GetFormFromFile(0x0005C84E, "Skyrim.esm") as Faction ; CurrentFollowerFaction
	Actor[] people = new Actor[64]
	int n = 0
	int i = 0
	While i < rated.Length && n < people.Length
		Actor a = rated[i] as Actor
		If a && !IsMinor(a) && StorageUtil.HasIntValue(a, "MantellaOSLA_Appetite") && people.Find(a) < 0
			people[n] = a
			n += 1
		EndIf
		i += 1
	EndWhile
	i = 0
	While i < nearby.Length && n < people.Length
		Actor a = nearby[i]
		If a && a != PlayerRef && !IsMinor(a) && a.IsInFaction(followers) && people.Find(a) < 0
			people[n] = a
			n += 1
		EndIf
		i += 1
	EndWhile
	; Ask the Arousal module about everyone first, so its answers come in while the list is read.
	i = 0
	While i < n
		RequestTier(people[i])
		i += 1
	EndWhile
	int[] counts = new int[3]
	string list = ""
	i = 0
	While i < n
		int tier = TierAnswer(people[i])
		counts[tier] = counts[tier] + 1
		If i < 18
			list += "\n" + people[i].GetDisplayName() + ": " + TierName(tier)
		EndIf
		i += 1
	EndWhile
	If n > 18
		list += "\n... and " + (n - 18) + " more"
	EndIf
	Return "Setup done: " + n + " NPCs set (" + counts[2] + " forward, " + counts[1] + " bold, " + counts[0] + " reserved)." + list + "\n\nChange anyone: aim at them and press the hotkey."
EndFunction

; The Arousal module decides the tier (it reads the overrides and defaults set here); without it, the override or
; the default, else reserved. Its script is never named here (a script that names a missing type never binds): it
; answers the mod event MLW_TierRequest by writing MLW_Tier (tier + 1) on the actor.
int Function TierOf(Actor akActor)
	RequestTier(akActor)
	Return TierAnswer(akActor)
EndFunction

; Clears the last answer, so a stale one (from before an override changed) is never read, then asks.
Function RequestTier(Actor akActor)
	If !ArousalLoaded()
		Return
	EndIf
	StorageUtil.UnsetIntValue(akActor, KEY_TIER)
	int handle = ModEvent.Create("MLW_TierRequest")
	If handle
		ModEvent.PushForm(handle, akActor)
		ModEvent.Send(handle)
	EndIf
EndFunction

; The Arousal module's answer to RequestTier (waits up to 2 seconds), else the override or default, else reserved.
int Function TierAnswer(Actor akActor)
	If ArousalLoaded()
		int tries = 0
		While !StorageUtil.HasIntValue(akActor, KEY_TIER) && tries < 10
			Utility.WaitMenuMode(0.2)
			tries += 1
		EndWhile
		int answer = StorageUtil.GetIntValue(akActor, KEY_TIER, 0)
		If answer > 0
			Return answer - 1
		EndIf
	EndIf
	int override = StorageUtil.GetIntValue(akActor, KEY_OVERRIDE, 0)
	If override > 0
		Return override - 1
	ElseIf MLW_TemperDefault.GetValueInt() > 0
		Return MLW_TemperDefault.GetValueInt() - 1
	EndIf
	Return 0
EndFunction

bool Function ArousalLoaded()
	Return Game.GetModByName(AROUSAL_PLUGIN) != 255 || Game.GetLightModByName(AROUSAL_PLUGIN) != 65535
EndFunction

; Children are never close and get no temperament. Some mods clear the child flag, so the race is checked too.
bool Function IsMinor(Actor akActor)
	If akActor.IsChild()
		Return true
	EndIf
	Race actorRace = akActor.GetRace()
	Return actorRace && StringUtil.Find(MiscUtil.GetRaceEditorID(actorRace), "Child") >= 0
EndFunction

string Function TierName(int aiTier)
	If aiTier == 2
		Return "forward"
	ElseIf aiTier == 1
		Return "bold"
	EndIf
	Return "reserved"
EndFunction
