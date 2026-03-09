"""Token authentication middleware for the local agent.

Checks for an ``Authorization: Token <key>`` header on every request.
If present and valid, sets ``request.user`` to the token's owner and marks
the request as token-authenticated (``request.is_token_auth = True``).

If the header is absent the request falls through to normal session auth,
so browser users are completely unaffected.
"""

from django.http import JsonResponse
from django.utils import timezone


class TokenAuthMiddleware:
    """Authenticate agent requests via ``Authorization: Token <key>``."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.is_token_auth = False

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Token '):
            token_key = auth_header[6:].strip()
            if not token_key:
                return JsonResponse(
                    {'error': 'Token missing after "Token " prefix.'},
                    status=401,
                )

            # Import here to avoid circular imports at module level
            from recovery.models import AgentToken

            try:
                agent_token = AgentToken.objects.select_related('user').get(
                    key=token_key,
                )
            except AgentToken.DoesNotExist:
                return JsonResponse(
                    {'error': 'Invalid or expired token.'},
                    status=401,
                )

            if not agent_token.is_active:
                return JsonResponse(
                    {'error': 'Token has been deactivated.'},
                    status=401,
                )

            # Authenticate the request
            request.user = agent_token.user
            request.is_token_auth = True

            # Update last_used_at (fire-and-forget, don't slow down the request)
            AgentToken.objects.filter(pk=agent_token.pk).update(
                last_used_at=timezone.now(),
            )

        response = self.get_response(request)
        return response
