import json
from datetime import timedelta

class MSTeamsTranscriptConverterPlugin:
    def __init__(self):
        self.current_speaker = None
        self.start_offset = None
        self.end_offset = None
        self.merged_text = ""

    def convert_timespan(self, time_str):
        """Convert the hh:mm:ss.ffffff format to a timedelta object."""
        hours, minutes, seconds = time_str.split(":")
        seconds, microseconds = map(float, seconds.split("."))
        return timedelta(hours=int(hours), minutes=int(minutes), seconds=int(seconds), microseconds=int(microseconds))

    def format_timespan(self, time_delta):
        """Format the timedelta object as hh:mm:ss."""
        total_seconds = int(time_delta.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def write_entry(self, start, end, speaker, text):
        """Format the merged entry for a speaker."""
        return f"[{start} - {end}] {speaker}\n{text}\n\n"

    def convert_transcript(self, json_file_path):
        """Convert the transcript from JSON to formatted text."""
        # Load the JSON content
        with open(json_file_path, 'r', encoding='utf-8') as f:
            transcript_data = json.load(f)

        # Initialize the result string
        result = ""

        # Iterate through the entries
        for entry in transcript_data['entries']:
            entry_start_offset = entry['startOffset']
            speaker_name = entry.get('speakerDisplayName', 'Speaker')
            text = entry['text']

            # Convert startOffset to timedelta and format it as hh:mm:ss
            entry_timespan = self.convert_timespan(entry_start_offset)
            formatted_entry_time = self.format_timespan(entry_timespan)

            # Check if the speaker is the same as the current speaker
            if speaker_name == self.current_speaker:
                # Same speaker, merge the text and update endOffset
                self.merged_text += f" {text}"
                self.end_offset = formatted_entry_time
            else:
                # New speaker, write the previous speaker's entry
                if self.current_speaker is not None:
                    result += self.write_entry(self.start_offset, self.end_offset, self.current_speaker, self.merged_text)

                # Start a new entry for the new speaker
                self.current_speaker = speaker_name
                self.start_offset = formatted_entry_time
                self.end_offset = formatted_entry_time
                self.merged_text = text

        # Write the last merged entry
        if self.current_speaker is not None:
            result += self.write_entry(self.start_offset, self.end_offset, self.current_speaker, self.merged_text)

        return result
    
    def get_tool_definition(self):
        return {
            'type': 'function',
            'function': {
                'name': "convert_transcript",
                'description': "Convert a Microsoft Teams transcript JSON file to formatted text.",
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'json_file_path': {
                            'type': 'string',
                            'description': 'The path to a local Microsoft Teams transcript JSON file, usually named streamContent.json.',
                        }
                    }
                },
                'required': ['json_file_path']
            }
        }
