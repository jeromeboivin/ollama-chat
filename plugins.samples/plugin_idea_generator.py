class IdeaGeneratorPlugin():
    def on_user_input_done(self, user_input, verbose_mode=False):
        if user_input and "/idea" in user_input:
            idea = user_input.replace("/idea", "").strip()
            return f"I have the following idea: '{idea}'. Please generate a list of questions that will help me refine this idea, one question at a time. Focus on aspects like clarity, feasibility, potential challenges, resources needed, and how it could be improved or expanded. The questions should guide me through thinking more deeply about how to implement or improve the idea."

        if user_input and "/search" in user_input:
            idea = user_input.replace("/search", "").strip()
            return f"I have chosen the following question to explore further: '{idea}'. Please generate a web search query that includes the context of the question and focuses on gathering relevant information or resources to help me find answers or solutions."

        return None
