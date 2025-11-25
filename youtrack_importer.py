import requests


class YouTrackImporter:
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url.rstrip('/')
        self.headers = {
            'Authorization': f'Bearer {api_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

    def _make_request(self, method: str, endpoint: str, data: dict | None = None,
                      params: dict | None = None) -> dict:
        url = f"{self.base_url}/api{endpoint}"
        response = requests.request(
            method=method,
            url=url,
            headers=self.headers,
            json=data,
            params=params
        )
        response.raise_for_status()

        if response.status_code == 204 or not response.content:
            return {}

        return response.json()

    def get_projects(self) -> list[dict]:
        return self._make_request('GET', '/admin/projects', params={'fields': 'id,name'})

    # get board columns and their states
    def get_board_states(self, board_id: str) -> dict[str, str]:
        board = self._make_request(
            'GET',
            f'/agiles/{board_id}',
            params={'fields': 'id,name,columnSettings(columns(presentation,fieldValues(name,id,$type),id,isResolved)),projects(id)'}
        )

        state_map = {}
        column_settings = board.get('columnSettings', {})
        columns = column_settings.get('columns', [])

        for column in columns:
            column_name = column.get('presentation', '')
            field_values = column.get('fieldValues', [])

            for field_value in field_values:
                state_name = field_value.get('name', '')
                if state_name:
                    state_map[column_name] = state_name
                    break

        return state_map

    def get_agile_boards(self, project_id: str | None = None) -> list[dict]:
        params = {'fields': 'id,name,projects(id,name)'}
        boards = self._make_request('GET', '/agiles', params=params)

        if project_id:
            return [b for b in boards if any(p.get('id') == project_id for p in b.get('projects', []))]

        return boards

    def create_issue(self, project_id: str, summary: str, description: str = "",
                    custom_fields: list[dict] | None = None,
                    mute_notifications: bool = True) -> dict:
        payload = {"summary": summary, "project": {"id": project_id}}

        if description:
            payload["description"] = description
        if custom_fields:
            payload["customFields"] = custom_fields

        params = {
            'fields': 'idReadable,summary,description,project(id,name)',
            'muteUpdateNotifications': str(mute_notifications).lower()
        }

        return self._make_request('POST', '/issues', data=payload, params=params)

    def add_comment(self, issue_id: str, comment_text: str,
                   author_id: str | None = None,
                   mute_notifications: bool = True) -> dict:
        payload = {"text": comment_text}
        if author_id:
            payload["author"] = {"id": author_id}

        params = {'muteUpdateNotifications': str(mute_notifications).lower()}

        try:
            return self._make_request('POST', f'/issues/{issue_id}/comments', data=payload, params=params)
        except Exception as e:
            if author_id and '403' in str(e):
                return self._make_request('POST', f'/issues/{issue_id}/comments',
                                         data={"text": comment_text}, params=params)
            raise

    def get_users(self) -> list[dict]:
        try:
            return self._make_request('GET', '/users', params={'fields': 'id,login,fullName,email'})
        except Exception:
            return []

    # assign multiple users to an issue
    def assign_issue_multiple(self, issue_id: str, user_logins: list[str]) -> dict | None:
        try:
            payload = {
                "customFields": [{
                    "name": "Assignee",
                    "$type": "MultiUserIssueCustomField",
                    "value": [{"login": login} for login in user_logins]
                }]
            }
            return self._make_request('POST', f'/issues/{issue_id}', data=payload,
                                     params={'fields': 'customFields(id,name,value(login))'})
        except Exception:
            return None

    def set_sprint(self, issue_id: str, sprint_name: str) -> dict | None:
        try:
            payload = {
                "customFields": [{
                    "name": "Sprints",
                    "$type": "MultiVersionIssueCustomField",
                    "value": [{"name": sprint_name}]
                }]
            }
            return self._make_request('POST', f'/issues/{issue_id}', data=payload,
                                     params={'fields': 'customFields(id,name,value(name))'})
        except Exception:
            return None

    def set_labels(self, issue_id: str, labels: list[str]) -> dict | None:
        if not labels:
            return None

        try:
            payload = {
                "customFields": [{
                    "name": "Label",
                    "$type": "MultiEnumIssueCustomField",
                    "value": [{"name": label} for label in labels]
                }]
            }
            return self._make_request('POST', f'/issues/{issue_id}', data=payload)
        except Exception:
            return None

    def set_story_points(self, issue_id: str, story_points: int) -> dict | None:
        if story_points is None:
            return None

        try:
            payload = {
                "customFields": [{
                    "name": "Story points",
                    "$type": "SimpleIssueCustomField",
                    "value": story_points
                }]
            }
            return self._make_request('POST', f'/issues/{issue_id}', data=payload)
        except Exception:
            return None

    def set_priority(self, issue_id: str, priority: str) -> dict | None:
        if not priority:
            return None

        try:
            payload = {
                "customFields": [{
                    "name": "Priority",
                    "$type": "SingleEnumIssueCustomField",
                    "value": {"name": priority}
                }]
            }
            return self._make_request('POST', f'/issues/{issue_id}', data=payload)
        except Exception:
            return None

    # import a trello card as youtrack issue
    def import_trello_card(self, project_id: str, card_data: dict,
                          state_map: dict | None = None,
                          user_map: dict | None = None,
                          yt_users: list[dict] | None = None,
                          sprint_name: str | None = None) -> dict:
        summary = card_data.get('Card Name', 'Untitled')
        description_parts = []

        if card_data.get('Description'):
            description_parts.append(card_data['Description'])
        if card_data.get('URL'):
            description_parts.append(f"\n**Original Trello Card:** {card_data['URL']}")
        if card_data.get('Checklists'):
            description_parts.append(f"\n**Checklists:**\n{card_data['Checklists']}")
        if card_data.get('Attachments'):
            description_parts.append(f"\n**Attachments:**\n{card_data['Attachments']}")

        github_sections = ['GitHub PRs', 'GitHub Issues', 'GitHub Commits']
        for section in github_sections:
            if card_data.get(section):
                description_parts.append(f"\n**{section}:**\n{card_data[section]}")

        powerup_sections = ['Google Drive Files']
        for section in powerup_sections:
            if card_data.get(section):
                description_parts.append(f"\n**{section}:**\n{card_data[section]}")

        description = "\n\n".join(description_parts)
        custom_fields = []

        trello_list = card_data.get('List', '')
        if state_map and trello_list in state_map:
            state_info = state_map[trello_list]
            state_name = state_info.get('name') if isinstance(state_info, dict) else state_info.get('name', state_info)

            custom_fields.append({
                "name": "State",
                "$type": "StateIssueCustomField",
                "value": {"name": state_name, "$type": "StateBundleElement"}
            })

        assignee_logins = []
        if user_map and yt_users:
            email_to_login = {user.get('email', '').lower(): user.get('login')
                            for user in yt_users if user.get('email') and user.get('login')}

            identifiers = []
            if card_data.get('Member Usernames'):
                identifiers.extend([u.strip().lower() for u in card_data['Member Usernames'].split(',') if u.strip()])
            if not identifiers and card_data.get('Members'):
                identifiers.extend([m.strip().lower() for m in card_data['Members'].split(',') if m.strip()])

            for identifier in identifiers:
                if identifier in user_map:
                    youtrack_email = user_map[identifier]
                    youtrack_login = email_to_login.get(youtrack_email.lower())
                    if youtrack_login:
                        assignee_logins.append(youtrack_login)

        issue = self.create_issue(
            project_id=project_id,
            summary=summary,
            description=description,
            custom_fields=custom_fields if custom_fields else None
        )

        issue_id = issue.get('idReadable')

        if assignee_logins:
            self.assign_issue_multiple(issue_id, assignee_logins)
        else:
            default_email = "alex.pykhteyev@gmail.com"
            if yt_users:
                email_to_login = {user.get('email', '').lower(): user.get('login')
                                for user in yt_users if user.get('email') and user.get('login')}
                default_login = email_to_login.get(default_email.lower())
                if default_login:
                    self.assign_issue_multiple(issue_id, [default_login])

        if sprint_name:
            self.set_sprint(issue_id, sprint_name)

        if card_data.get('Labels'):
            labels = [l.strip() for l in card_data['Labels'].split(',') if l.strip()]
            if labels:
                self.set_labels(issue_id, labels)

        if card_data.get('Priority'):
            priority = card_data['Priority'].strip()
            if priority:
                self.set_priority(issue_id, priority)

        sp_value = card_data.get('Story Points', '').strip()
        if sp_value:
            try:
                story_points = int(sp_value)
                if story_points >= 0:
                    self.set_story_points(issue_id, story_points)
            except (ValueError, TypeError):
                pass

        if card_data.get('Comments'):
            try:
                comments = card_data['Comments'].split('\n---\n')
                for comment in comments:
                    if comment.strip():
                        self.add_comment(issue_id, comment.strip())
            except Exception:
                pass

        if card_data.get('Due Date'):
            try:
                due_status = " (Completed)" if card_data.get('Due Complete') == 'Yes' else ""
                self.add_comment(issue_id, f"**Due date from Trello:** {card_data['Due Date']}{due_status}")
            except Exception:
                pass

        return issue
