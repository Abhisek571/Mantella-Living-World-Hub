Scriptname ConsoleUtil Hidden
{Compile stub: what the Console button calls (ConsoleUtilSSE NG, a soft requirement). The real script binds at runtime.}
int Function GetVersion() global native
string Function ReadMessage() global native
Function PrintMessage(string a_message) global native
Function ExecuteCommand(string a_command) global native
ObjectReference Function GetSelectedReference() global native
Function SetSelectedReference(ObjectReference a_reference) global native
