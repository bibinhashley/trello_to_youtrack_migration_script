# Trello to YouTrack Migration Script

This script helps you move your Trello boards to YouTrack. It copies everything - cards, comments, attachments, labels, and even checklists.

## What you need

1. Your Trello API key and token
2. Your YouTrack instance URL and token
3. Python 3.7 or newer

## How to run it

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file with your credentials (use `.env.example` as a template)

3. Run the script:
```bash
python migrate.py
```

4. Pick the board you want to migrate and let it do its thing!

## User Mapping

If you want to map Trello users to YouTrack users, create a `user_mapping.json` file with Trello user IDs pointing to YouTrack logins.

That's it! The script will create a new YouTrack project and move everything over.
