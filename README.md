# Life Assistant

A personal AI assistant you run on your own machine. It is one app for chat,
tasks, reminders, knowledge, skills, voice, and agent work you can actually
inspect.

## What makes it different

- **Autonomous task work.** The assistant can turn a request into a task,
  work on it in the background, pause when it needs your input, and hand the
  result back to the main chat. Tasks can run now, later, or on a recurring
  schedule.
- **Observable by default.** Tool calls, task chats, accumulated knowledge,
  skills, and assistant progress are visible in the UI instead of hidden behind
  one opaque chat stream.
- **Voice and notifications.** You can type or talk to the assistant, and push
  notifications let reminders, handoffs, and important task updates reach you
  even when the app is not open.
- **Approval-gated self-improvement.** The assistant can notice mistakes or
  recurring patterns and propose durable improvements. Those improvements land
  in memory or skills only after you approve them, so it can get better without
  quietly overfitting to one bad example.

Memory is split deliberately: core memory holds stable facts and preferences,
knowledge notes hold longer user-visible material, and skills teach the
assistant how to handle specific kinds of work.

## Use cases

Dump tasks and ideas into the agent without being blocked or things becoming messy:

 - "Remind me Saturday morning to get groceries." — sets a scheduled task, the reminder lands in chat Saturday.
 - "Research the best espresso machine under €500, get back to me." — runs in the background, comes back with a recommendation.
 - "Do these 5 things: ..." — five separate tasks, each running on its own.
 - "Save the action items from /tmp/meeting.md as a note." — reads the file off the machine, keeps a knowledge note.

{show gif}

More worked examples: [`docs/cases/`](docs/cases/).


## Notes
This is still quite early in development. It is working but might not be fully clean
and smooth.


## Security

The project is an agent who has full control of a machine and full web access,
that is what makes it powerful, but with that there are also safety risks.
I did not want to limit capabilities or add complexity for security.
Prompt injection protection is something I would still add.
Otherwise I suggest those measures:
 - Don't give your agent any information that cannot become public in the worst case
 - Don't let it do any truly destructive things. Backup the information on the machine, give it limited access to github and other platforms


## Setup

Supported target: a fresh **Ubuntu 24.04 VPS** — root SSH access, public IP, port 8000 open.

1. SSH in as root.
2. Run the installer. It clones the repo, installs dependencies, sets up the
   systemd services, and prints a generated login password at the end — save it.

   ```bash
   curl -fsSL https://raw.githubusercontent.com/Philipp258/life-assistant/main/deploy/install.sh \
     | LIFE_ASSISTANT_REPO_URL=https://github.com/Philipp258/life-assistant.git bash
   ```

3. Restart once the install finishes:

   ```bash
   systemctl restart life-assistant
   ```

4. Open `http://<vps-ip>:8000/`, sign in with the printed password, and
   finish provider setup in the UI.

Supported chat providers:

- z.ai
- OpenRouter
- OpenAI API
- ChatGPT subscription through Codex auth

OpenRouter is also used for voice transcription and can be used for voice
replies; without it, spoken replies fall back to the browser's built-in voice.

Push notifications and microphone access need HTTPS. Without a domain, use
the Tailscale guide in [`deploy/README.md`](deploy/README.md), which also
covers updates, backups, and the file layout.
