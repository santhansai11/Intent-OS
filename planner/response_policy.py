"""Shared answer-vs-export behavior for all planning providers."""

CONVERSATION_GUIDANCE = '''For information, explanation, advice, comparison, or summarization requests,
answer directly in the finish summary with the useful response and any verified sources.
Do not require a save location, filename, format, or file creation to answer a question.
Use document_export/files_write or other storage tools only when the user explicitly asks
for a saved file, export, report artifact, or another operation that actually needs storage.
The presence of output_folder, a workspace, or an output grant is not a request to save.
When a user asks to save or export, honor that request and the selected output settings.
Ask only for information necessary to answer or perform the actual requested action.'''
