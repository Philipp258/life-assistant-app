# Life Assistant

A personal AI assistant controlling its own machine like Openclaw,
but with some changes and extensions I was personally missing:

 - highly interactive, non blocking main chat.
  Real work happens in an observerable steerable task a subagent is working on.
 So you can continously give it tasks without having to wait.
 ![Screenshot 2026-05-31 at 19.00.59.png](readme/Screenshot%202026-05-31%20at%2019.00.59.png)
The approach is similar to https://thinkingmachines.ai/blog/interaction-models/ though more simple and not as interactive.
 - A task system the agent can manage for you. Tasks can be assigned to you are the assistant and support scheduling and repeating
 - Goals as a way to group tasks and determine next steps
 - An integrated file system like knowledge feature the assistant can manage for you
 - Everything is observeable. Core memory, skills, knowldge, regular tasks, tools calls, etc.
 - Approval gated self learning. I found most self learning systems tend to overfit to cases
and build invisble unwanted rules. Life assistant agent is collecting and suggesting improvments
regularly, but never without supervision.
 - Experimental call feature for main chat


## Notes
This is still quite early in development. It is working but might not be fully clean
and smooth. Especially self learning and voice calls are still
being discovered


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
   curl -fsSL https://raw.githubusercontent.com/Philipp258/life-assistant-app/main/deploy/install.sh \
     | LIFE_ASSISTANT_REPO_URL=https://github.com/Philipp258/life-assistant-app.git bash
   ```

   If sslip.io is temporarily rate-limited by Let's Encrypt, point your own DNS
   name at the VPS and rerun with `LIFE_ASSISTANT_DOMAIN=your.name.example`.

3. Open the URL printed at the end of the installer, sign in with the printed
   password, and finish provider setup in the UI.

   For ChatGPT subscription auth, the UI shows the server command to run:

   ```bash
   env HOME=/root codex login --device-auth
   ```

   After that command succeeds on the VPS, return to the UI and import the
   server Codex login.

Supported chat providers:

- z.ai
- OpenRouter
- OpenAI API
- ChatGPT subscription through Codex auth

Currently I find Openai subscription to work best.
To use voice calls with a good voice, Openrouter is needed
to do text to speech. Normally it does not cost much credit.
