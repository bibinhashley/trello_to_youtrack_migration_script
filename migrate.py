from trello_exporter import TrelloExporter
from youtrack_importer import YouTrackImporter
import sys
import os
from datetime import datetime
import csv
import json
from dotenv import load_dotenv


class Migration:
    def __init__(self, trello_api_key: str, trello_token: str,
                 youtrack_url: str, youtrack_token: str):
        self.trello = TrelloExporter(trello_api_key, trello_token)
        self.youtrack = YouTrackImporter(youtrack_url, youtrack_token)
        self.youtrack_url = youtrack_url
        self.user_mapping = {}

        try:
            with open('user_mapping.json', 'r') as f:
                mapping_data = json.load(f)
                for username, data in mapping_data.items():
                    trello_fullname = data.get('trello_fullname', '')
                    if trello_fullname:
                        self.user_mapping[username.lower()] = trello_fullname
                        trello_api_fullname = data.get('trello_fullname', '').lower()
                        if trello_api_fullname:
                            self.user_mapping[trello_api_fullname] = trello_fullname
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def extract_card_id_from_url(self, url_or_id: str) -> str:
        url_or_id = url_or_id.strip()
        if '/c/' in url_or_id:
            parts = url_or_id.split('/c/')
            if len(parts) > 1:
                card_id = parts[1].split('/')[0]
                return card_id
        return url_or_id

    def fetch_cards_by_ids(self, card_ids_or_urls: list[str]) -> tuple[list[dict], list[str]]:
        cards = []
        extracted_ids = []
        for item in card_ids_or_urls:
            card_id = self.extract_card_id_from_url(item)
            try:
                card = self.trello.get_card_details(card_id)
                cards.append(card)
                extracted_ids.append(card_id)
            except Exception:
                print(f"Failed to fetch: {item}")
        return cards, extracted_ids

    def fetch_cards_from_list(self, board_id: str, list_name: str) -> list[dict]:
        board_data = self.trello.get_board_data(board_id)
        lists_map = {lst['id']: lst['name'] for lst in board_data.get('lists', [])}
        cards = board_data.get('cards', [])

        for list_id, name in lists_map.items():
            if name == list_name:
                return [c for c in cards if c.get('idList') == list_id and not c.get('closed')]
        return []

    def get_all_lists_with_cards(self, board_id: str) -> dict[str, list[dict]]:
        board_data = self.trello.get_board_data(board_id)
        lists_map = {lst['id']: lst['name'] for lst in board_data.get('lists', [])}
        cards = board_data.get('cards', [])

        lists_with_cards = {}
        for list_id, list_name in lists_map.items():
            list_cards = [c for c in cards if c.get('idList') == list_id and not c.get('closed')]
            if list_cards:
                lists_with_cards[list_name] = list_cards

        return lists_with_cards

    def pick_target_state(self, board_id: str, suggested_name: str = None) -> str | None:
        existing_columns = self.get_board_columns(board_id)

        if suggested_name:
            print(f"\nTarget column for '{suggested_name}':")
        else:
            print(f"\nAvailable columns in YouTrack:")

        if not existing_columns:
            return None

        column_list = list(existing_columns.keys())
        for i, column_name in enumerate(column_list, 1):
            state_name = existing_columns[column_name]
            print(f"  {i}. {column_name} (State: {state_name})")

        while True:
            choice = input(f"\nSelect column (1-{len(column_list)}): ").strip()
            try:
                i = int(choice) - 1
                if 0 <= i < len(column_list):
                    selected_column = column_list[i]
                    return existing_columns[selected_column]
            except ValueError:
                pass

    def get_board_columns(self, board_id: str) -> dict[str, str]:
        try:
            return self.youtrack.get_board_states(board_id)
        except Exception:
            return {}

    def prepare_cards_for_import(self, cards: list[dict], list_name: str, board_name: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_csv = f"temp_migration_{timestamp}.csv"

        card_data = []
        for card in cards:
            try:
                detailed_card = self.trello.get_card_details(card['id'])
            except Exception:
                detailed_card = card

            members = detailed_card.get('members', [])
            member_names = self.trello.format_members(members)
            member_usernames = ', '.join([m.get('username', '') for m in members if m.get('username')])
            member_emails = ', '.join([m.get('email', '') for m in members if m.get('email')])

            comments_data = self.trello.get_card_comments(card['id'])
            formatted_comments = []
            for comment in comments_data:
                member_creator = comment.get('memberCreator', {})
                trello_username = member_creator.get('username', '')
                trello_fullname_field = member_creator.get('fullName', '')

                author = 'Unknown'
                if trello_username and trello_username.lower() in self.user_mapping:
                    author = self.user_mapping[trello_username.lower()]
                elif trello_fullname_field and trello_fullname_field.lower() in self.user_mapping:
                    author = self.user_mapping[trello_fullname_field.lower()]
                elif trello_fullname_field:
                    author = trello_fullname_field

                text = comment.get('data', {}).get('text', '')
                date = comment.get('date', '')
                if text:
                    formatted_comments.append(f"[{author} on {date}]\n{text}")
            comments_str = '\n---\n'.join(formatted_comments) if formatted_comments else ''

            plugin_data = detailed_card.get('pluginData', [])

            trello_priority = self.trello.get_card_priority(plugin_data=plugin_data)
            youtrack_priority = ''
            if trello_priority:
                youtrack_priority = self.trello.map_trello_priority_to_youtrack(trello_priority)

            story_points = self.trello.get_card_story_points(plugin_data=plugin_data)

            row = {
                'Board': board_name,
                'List': list_name,
                'Card ID': card.get('id', ''),
                'Card Name': card.get('name', ''),
                'Description': card.get('desc', ''),
                'Due Date': card.get('due', ''),
                'Due Complete': 'Yes' if card.get('dueComplete') else 'No',
                'Labels': self.trello.format_labels(card.get('labels', [])),
                'Priority': youtrack_priority,
                'Story Points': story_points if story_points is not None else '',
                'Members': member_names,
                'Member Emails': member_emails,
                'Member Usernames': member_usernames,
                'URL': card.get('shortUrl', ''),
                'Archived': 'No',
                'Attachments': self.trello.format_attachments(detailed_card.get('attachments', [])),
                'Checklists': self.trello.format_checklist_data(detailed_card.get('checklists', [])),
                'Comments': comments_str,
            }

            attachments = detailed_card.get('attachments', [])
            powerup_links = self.trello.extract_powerup_links(attachments)
            powerup_links.pop('Other Links', None)
            row.update(powerup_links)

            card_data.append(row)

        fieldnames = list(card_data[0].keys()) if card_data else []

        with open(temp_csv, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(card_data)

        return temp_csv

    def import_cards_to_youtrack(self, temp_csv: str, target_state: str,
                                project_id: str, source_label: str,
                                sprint_name: str | None = None) -> list[dict]:
        user_map = {}
        try:
            with open('user_mapping.json', 'r') as f:
                trello_mapping = json.load(f)
                for trello_username, data in trello_mapping.items():
                    youtrack_email = data.get('youtrack_email', '').strip()
                    if youtrack_email:
                        if trello_username:
                            user_map[trello_username.lower()] = youtrack_email.lower()

                        trello_fullname = data.get('trello_fullname', '').strip()
                        if trello_fullname and trello_fullname.lower() != trello_username.lower():
                            user_map[trello_fullname.lower()] = youtrack_email.lower()
        except (FileNotFoundError, Exception):
            pass

        state_map = {
            source_label: {
                'name': target_state,
                'column': target_state
            }
        }

        created_issues = []
        yt_users = self.youtrack.get_users()

        with open(temp_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            cards_to_import = list(reader)

        print(f"\nImporting {len(cards_to_import)} cards...")

        for i, card in enumerate(cards_to_import, 1):
            try:
                issue = self.youtrack.import_trello_card(
                    project_id,
                    card,
                    state_map,
                    user_map=user_map,
                    yt_users=yt_users,
                    sprint_name=sprint_name
                )
                created_issues.append(issue)
            except Exception:
                print(f"[{i}] Failed: {card.get('Card Name', 'Unnamed')}")

        try:
            os.remove(temp_csv)
        except Exception:
            pass

        print(f"\nDone: {len(created_issues)}/{len(cards_to_import)} imported to '{target_state}'")
        return created_issues

    def import_cards(self, board_id: str, card_ids: list[str],
                    target_state: str, project_id: str,
                    sprint_name: str | None = None) -> list[dict]:
        print(f"\nFetching {len(card_ids)} cards...")
        cards, extracted_ids = self.fetch_cards_by_ids(card_ids)

        if not cards:
            print("No valid cards found")
            return []

        print(f"Found {len(cards)} cards: {', '.join(extracted_ids)}")

        board_data = self.trello.get_board_data(board_id)
        board_name = board_data.get('name', 'Unknown Board')

        temp_csv = self.prepare_cards_for_import(cards, "Selected Cards", board_name)
        return self.import_cards_to_youtrack(temp_csv, target_state, project_id, "Selected Cards", sprint_name)

    def import_list(self, board_id: str, list_name: str,
                   target_state: str, project_id: str,
                   sprint_name: str | None = None) -> list[dict]:
        trello_cards = self.fetch_cards_from_list(board_id, list_name)

        if not trello_cards:
            print(f"No cards found in Trello list '{list_name}'")
            return []

        trello_board_data = self.trello.get_board_data(board_id)
        trello_board_name = trello_board_data.get('name', 'Unknown Board')

        temp_csv = self.prepare_cards_for_import(trello_cards, list_name, trello_board_name)
        return self.import_cards_to_youtrack(temp_csv, target_state, project_id, list_name, sprint_name)


def ask_method_mode() -> str:
    print("\nHow do you want to migrate?")
    print("  1. Specific cards (URLs or IDs)")
    print("  2. Entire list")

    while True:
        choice = input("\nChoice (1-2): ").strip()
        if choice == '1':
            return 'cards'
        elif choice == '2':
            return 'list'


def main():
    print("Trello to YouTrack\n")

    load_dotenv()

    TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
    TRELLO_TOKEN = os.getenv("TRELLO_API_TOKEN")
    TRELLO_BOARD_ID = os.getenv("TRELLO_BOARD_ID")
    YOUTRACK_URL = os.getenv("YOUTRACK_URL")
    YOUTRACK_TOKEN = os.getenv("YOUTRACK_API_TOKEN")
    TRELLO_CARD_IDS = os.getenv("TRELLO_CARD_IDS", "").strip()

    if not all([TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_BOARD_ID]):
        print("Missing Trello config in .env")
        sys.exit(1)

    if not YOUTRACK_TOKEN or YOUTRACK_TOKEN == "your-youtrack-token-here":
        print("Missing YOUTRACK_API_TOKEN in .env")
        sys.exit(1)

    migration = Migration(
        TRELLO_API_KEY, TRELLO_TOKEN,
        YOUTRACK_URL, YOUTRACK_TOKEN
    )

    try:
        youtrack_projects = migration.youtrack.get_projects()
        if not youtrack_projects:
            print("No YouTrack projects found")
            sys.exit(1)

        print("YouTrack Projects:")
        for i, project in enumerate(youtrack_projects, 1):
            print(f"  {i}. {project.get('name')}")

        while True:
            choice = input(f"\nSelect YouTrack project:").strip()
            try:
                i = int(choice) - 1
                if 0 <= i < len(youtrack_projects):
                    target_project = youtrack_projects[i]
                    break
            except ValueError:
                pass

        project_id = target_project['id']

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    try:
        youtrack_boards = migration.youtrack.get_agile_boards(project_id)
        if not youtrack_boards:
            print("No YouTrack agile boards found")
            sys.exit(1)

        print("\nYouTrack Agile Boards:")
        for i, board in enumerate(youtrack_boards, 1):
            print(f"  {i}. {board.get('name')}")

        while True:
            choice = input(f"\nSelect YouTrack board:").strip()
            try:
                i = int(choice) - 1
                if 0 <= i < len(youtrack_boards):
                    target_board = youtrack_boards[i]
                    break
            except ValueError:
                pass

        board_id = target_board['id']

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Ask for sprint number once
    sprint_input = input("\nEnter Sprint number (e.g., 6, 7) or leave empty to skip: ").strip()
    sprint_name = f"Sprint {sprint_input}" if sprint_input else None

    method = ask_method_mode()

    if method == 'cards':
        card_ids_input = input("\nEnter URLs or IDs (comma separated): ").strip()
        card_ids = [cid.strip() for cid in card_ids_input.split(',') if cid.strip()]

        if not card_ids:
            print("No card ids provided")
            sys.exit(1)

        extracted_ids = [migration.extract_card_id_from_url(cid) for cid in card_ids]

        target_state = migration.pick_target_state(board_id)
        if not target_state:
            print("No state selected")
            sys.exit(1)

        print(f"\nCards: {', '.join(extracted_ids)}")
        confirm = input(f"Import {len(extracted_ids)} cards to '{target_state}'? (y/n): ").strip().lower()
        if confirm in ['yes', 'y']:
            migration.import_cards(TRELLO_BOARD_ID, extracted_ids, target_state, project_id, sprint_name)

    else:
        trello_lists_with_cards = migration.get_all_lists_with_cards(TRELLO_BOARD_ID)

        print(f"\nAvailable Trello lists:")
        trello_list_names = sorted(trello_lists_with_cards.keys())
        for i, list_name in enumerate(trello_list_names, 1):
            card_count = len(trello_lists_with_cards[list_name])
            print(f"  {i}. {list_name} ({card_count} cards)")

        choice = input(f"\nSelect Trello list:").strip()

        try:
            i = int(choice) - 1
            if 0 <= i < len(trello_list_names):
                selected_list = trello_list_names[i]
            else:
                print("Invalid selection")
                sys.exit(1)
        except ValueError:
            print("Invalid number")
            sys.exit(1)

        target_state = migration.pick_target_state(board_id, selected_list)
        if not target_state:
            print("No state selected")
            sys.exit(1)

        print(f"\n'{selected_list}' ({len(trello_lists_with_cards[selected_list])} cards) -> '{target_state}'")
        confirm = input("Import? (y/n): ").strip().lower()

        if confirm in ['yes', 'y']:
            migration.import_list(TRELLO_BOARD_ID, selected_list, target_state, project_id, sprint_name)

    print(f"\nDone")


if __name__ == "__main__":
    main()
