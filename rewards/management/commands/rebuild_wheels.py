from django.core.management.base import BaseCommand
from accounts.models import Company
from rewards.services.probabilities import get_or_build_wheel, DEFAULT_WEIGHTS

class Command(BaseCommand):
    help = "Reconstruit/initialise les roues de probabilité pour chaque entreprise."

    def handle(self, *args, **opts):
        for c in Company.objects.filter(is_active=True):
            wheel = get_or_build_wheel(c, DEFAULT_WEIGHTS)
            self.stdout.write(self.style.SUCCESS(f"{c.name}: {wheel.key} ({wheel.size} cases)"))
