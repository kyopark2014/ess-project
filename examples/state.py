from strands import Agent, tool, ToolContext

# 초기 상태로 에이전트 생성
agent = Agent(state={
    "user_preferences": {"theme": "dark"},
    "session_count": 0
})

# 상태 접근
theme = agent.state.get("user_preferences")
print(theme)  # {"theme": "dark"}

# 상태 설정
agent.state.set("last_action", "login")
agent.state.set("session_count", 1)

# 전체 상태 조회
all_state = agent.state.get()
print(all_state)

# 상태 삭제
agent.state.delete("last_action")
