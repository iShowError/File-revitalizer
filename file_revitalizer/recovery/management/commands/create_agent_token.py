"""Management command to create an API token for the local agent.

Usage:
    python manage.py create_agent_token <username>
    python manage.py create_agent_token <username> --label "home-server"
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User

from recovery.models import AgentToken


class Command(BaseCommand):
    help = 'Create an API token for authenticating the local agent.'

    def add_arguments(self, parser):
        parser.add_argument(
            'username',
            help='Username of the token owner.',
        )
        parser.add_argument(
            '--label',
            default='',
            help='Optional label for this token (e.g. "home-server").',
        )

    def handle(self, *args, **options):
        username = options['username']
        label = options['label']

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f'User "{username}" does not exist.')

        token = AgentToken(user=user, label=label)
        token.save()

        self.stdout.write(
            self.style.SUCCESS(f'\nToken created for user "{username}":')
        )
        self.stdout.write(f'\n  {token.key}\n')
        self.stdout.write(
            self.style.WARNING(
                'Save this token now — it will not be shown again in full.\n'
                'Set it as AGENT_API_TOKEN in the agent\'s .env file.'
            )
        )
