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

Supported target: a fresh **Ubuntu/Debian-style systemd VPS** with `apt`,
root SSH access, public IP, and ports 80 and 443 open.

1. SSH in as root.
2. Run the installer. It clones the repo, installs dependencies, derives a
   stable `https://<your-ip-with-dashes>.sslip.io` URL, issues a Let's Encrypt
   certificate, sets up the systemd services, and prints the URL plus a
   generated login password at the end — save them.

   ```bash
   curl -fsSL https://raw.githubusercontent.com/Philipp258/life-assistant/main/deploy/install.sh \
     | LIFE_ASSISTANT_REPO_URL=https://github.com/Philipp258/life-assistant.git bash
   ```

   If sslip.io is temporarily rate-limited by Let's Encrypt, point your own DNS
   name at the VPS and rerun with `LIFE_ASSISTANT_DOMAIN=your.name.example`.

3. Open the URL printed at the end of the installer, sign in with the printed
   password, and finish provider setup in the UI.

   For ChatGPT subscription auth, the UI shows the server command to run:

   ```bash
   sudo -u life-assistant -H env HOME=/home/life-assistant codex login --device-auth
   ```

   After that command succeeds on the VPS, return to the UI and import the
   server Codex login.

Supported chat providers:

- z.ai
- OpenRouter
- OpenAI API
- ChatGPT subscription through Codex auth

OpenRouter is also used for voice transcription and can be used for voice
replies; without it, spoken replies fall back to the browser's built-in voice.

The default install gives you real HTTPS without buying a domain: sslip.io
resolves `1-2-3-4.sslip.io` straight back to your VPS IP, and the cert is
issued by Let's Encrypt directly to your machine, so traffic stays end-to-end
between your browser and the server. If you prefer your own domain, or a
tailnet-only deployment via Tailscale, see [`deploy/README.md`](deploy/README.md).
