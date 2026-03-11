from django.utils import timezone

from .models import Agent


def agent_status(request):
    """Inject agent online/offline status into every template context."""
    if not request.user.is_authenticated:
        return {}
    threshold = timezone.now() - timezone.timedelta(minutes=2)
    online = Agent.objects.filter(
        user=request.user, is_active=True,
        last_heartbeat__gte=threshold,
    ).exists()
    return {'nav_agent_online': online}
