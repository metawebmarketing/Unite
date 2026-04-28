from django.contrib import admin

from apps.messaging.models import DMMessage, DMThread, DMThreadParticipant

admin.site.register(DMThread)
admin.site.register(DMThreadParticipant)
admin.site.register(DMMessage)
