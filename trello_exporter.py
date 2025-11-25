import requests
import json


class TrelloExporter:
    BASE_URL = "https://api.trello.com/1"

    def __init__(self, api_key: str, api_token: str):
        self.auth_params = {'key': api_key, 'token': api_token}

    def get_board_data(self, board_id: str) -> dict:
        url = f"{self.BASE_URL}/boards/{board_id}"
        params = {
            **self.auth_params,
            'cards': 'all',
            'lists': 'all',
            'members': 'all',
            'fields': 'all',
            'customFields': 'true'
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_card_details(self, card_id: str) -> dict:
        url = f"{self.BASE_URL}/cards/{card_id}"
        params = {
            **self.auth_params,
            'attachments': 'true',
            'checklists': 'all',
            'customFieldItems': 'true',
            'members': 'true',
            'pluginData': 'true',
            'actions': 'commentCard',
            'fields': 'all'
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_card_comments(self, card_id: str) -> list[dict]:
        url = f"{self.BASE_URL}/cards/{card_id}/actions"
        params = {
            **self.auth_params,
            'filter': 'commentCard'
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception:
            return []

    # format checklists for export
    def format_checklist_data(self, checklists: list[dict]) -> str:
        if not checklists:
            return ""

        formatted = []
        for checklist in checklists:
            name = checklist.get('name', '')
            items = checklist.get('checkItems', [])
            checklist_str = f"{name}:"
            for item in items:
                status = "✓" if item.get('state') == 'complete' else "☐"
                checklist_str += f"\n  {status} {item.get('name', '')}"
            formatted.append(checklist_str)

        return "\n\n".join(formatted)

    def format_attachments(self, attachments: list[dict]) -> str:
        if not attachments:
            return ""

        formatted = []
        for att in attachments:
            name = att.get('name', '')
            url = att.get('url', '')
            formatted.append(f"{name}: {url}")

        return "\n".join(formatted)

    # extract links from powerup attachments
    def extract_powerup_links(self, attachments: list[dict], markdown_format: bool = True) -> dict[str, str]:
        powerup_data = {
            'GitHub PRs': [],
            'GitHub Issues': [],
            'GitHub Commits': [],
            'Google Drive Files': [],
            'Other Links': []
        }

        def format_link(name: str, url: str) -> str:
            if markdown_format:
                return f"[{name}]({url})"
            return f"{name} - {url}"

        for att in attachments:
            url = att.get('url', '')
            name = att.get('name', '')
            is_upload = att.get('isUpload', False)

            if is_upload:
                continue

            url_lower = url.lower()

            if 'github.com' in url_lower:
                if '/pull/' in url:
                    powerup_data['GitHub PRs'].append(format_link(name, url))
                elif '/issues/' in url:
                    powerup_data['GitHub Issues'].append(format_link(name, url))
                elif '/commit/' in url:
                    powerup_data['GitHub Commits'].append(format_link(name, url))
            elif 'drive.google.com' in url_lower or 'docs.google.com' in url_lower:
                powerup_data['Google Drive Files'].append(format_link(name, url))
            elif url and not is_upload:
                powerup_data['Other Links'].append(format_link(name, url))

        result = {}
        for key, values in powerup_data.items():
            if values:
                result[key] = "\n".join(values)

        return result

    def format_members(self, members: list[dict]) -> str:
        if not members:
            return ""
        return ", ".join([m.get('fullName', m.get('username', '')) for m in members])

    def format_labels(self, labels: list[dict]) -> str:
        if not labels:
            return ""
        return ", ".join([l.get('name', l.get('color', '')) for l in labels])

    # get story points from card size powerup
    def get_card_story_points(self, card_id: str | None = None, plugin_data: list[dict] | None = None) -> int | None:
        try:
            CARD_SIZE_PLUGIN_ID = "5cd476e1efce1d2e0cbe53a8"

            if plugin_data is None and card_id:
                detailed = self.get_card_details(card_id)
                plugin_data = detailed.get('pluginData', [])

            if not plugin_data:
                return None

            for entry in plugin_data:
                if entry.get('idPlugin') == CARD_SIZE_PLUGIN_ID:
                    value_str = entry.get('value', '')
                    if value_str:
                        try:
                            parsed = json.loads(value_str)
                            size = parsed.get('size') or parsed.get('points') or parsed.get('estimate')
                            if size is not None:
                                return int(size)
                        except:
                            pass
            return None
        except:
            return None

    def get_card_priority(self, card_id: str | None = None, plugin_data: list[dict] | None = None) -> str | None:
        try:
            CARD_PRIORITY_PLUGIN_ID = "5d40dbf16b5f44535df106d1"

            if plugin_data is None and card_id:
                detailed = self.get_card_details(card_id)
                plugin_data = detailed.get('pluginData', [])

            if not plugin_data:
                return None

            for entry in plugin_data:
                if entry.get('idPlugin') == CARD_PRIORITY_PLUGIN_ID:
                    value_str = entry.get('value', '')
                    if value_str:
                        try:
                            parsed = json.loads(value_str)
                            priority = parsed.get('priority')
                            if priority:
                                return str(priority)
                        except:
                            pass
            return None
        except:
            return None

    # map trello priority numbers to youtrack priority names
    def map_trello_priority_to_youtrack(self, trello_priority: str) -> str:
        priority_map = {
            "1": "Highest",
            "2": "Critical",
            "3": "High",
            "4": "Medium",
            "5": "Low"
        }
        return priority_map.get(str(trello_priority), "Medium")
