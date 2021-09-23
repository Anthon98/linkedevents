# -*- coding: utf-8 -*-

# Dependencies.

# RDFLIB:
import rdflib
from rdflib import RDF
from rdflib.namespace import DCTERMS, OWL, SKOS

# HTTP Requests:
import requests

# Logging:
import os
import logging
from os import mkdir
from os.path import abspath, join, dirname, exists, basename, splitext

# Django:
from django_orghierarchy.models import Organization
from django_orghierarchy.models import OrganizationClass
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from events.models import Keyword, KeywordLabel, DataSource, BaseModel, Language

# Importer specific:
from .base import Importer, register_importer


# Setup Logging:
if not exists(join(dirname(__file__), 'logs')):
    mkdir(join(dirname(__file__), 'logs'))

logger = logging.getLogger(__name__)  # Per module logger
curFileExt = basename(__file__)
curFile = splitext(curFileExt)[0]
logFile = \
    logging.FileHandler(
        '%s' % (join(dirname(__file__), 'logs', curFile+'.logs'))
    )
logFile.setFormatter(
    logging.Formatter(
        '[%(asctime)s] <%(name)s> (%(lineno)d): %(message)s'
    )
)
logFile.setLevel(logging.DEBUG)
logger.addHandler(
    logFile
)

# Create a new importer class.
@register_importer
class JupoImporter(Importer):
    # Importer class dependant attributes:
    name = "juponew" # Command calling name.
    supported_languages = ['fi', 'sv', 'en'] # Base file requirement.

    def iterator(self, data, key, query, obj_model, attr_map, phase=None) -> None:
        for idx, sub_key in enumerate(data[key]):
            try:
                q_obj = query()
                for count, attr in enumerate(obj_model):
                    setattr(q_obj, attr, data[key][sub_key][count])
                q_obj.save()
                setattr(self, attr_map[idx], query.objects.get(id=data[key][sub_key][0]))
                if phase:
                    if sub_key in data['org']:
                        data['org'][sub_key][-1] = getattr(self, attr_map[idx])
                    else:
                        data['orgclass']['orgclass'][-1] = getattr(self, attr_map[idx])
            except Exception as e:
                logger.error(e)

    # Setup our class attributes & Add to DB.
    def setup(self) -> None:
        # Data mapped by models order:
        data = {
            'ds': {
                'yso': ['yso', 'Yleinen suomalainen ontologia', True],
                'jupo': ['jupo', 'Julkisen hallinnon palveluontologia', True],
                'org': ['org', 'Ulkoa tuodut organisaatiotiedot', True],
            },
            'org': {
                'yso': ['yso:1200', '1200', 'YSO', BaseModel.now(), 'org:13', None],
                'jupo': ['jupo:1300', '1300', 'JUPO', BaseModel.now(), 'org:13', None],
            },
            'orgclass': {
                'orgclass': ['org:13', '13', 'Sanasto', BaseModel.now(), None],
            },
            # Attribute mapping for org due to class related attributes.
            'attr_maps': {
                'ds': ('data_source', 'data_source_jupo', 'data_source_org'),
                'org': ('organization', 'organization_jupo'),
                'orgclass': ('organization_class_13'),
            },
            # Models for easy iteration (Selected attributes):
            'model_maps': {
                'ds': ('id', 'name', 'user_editable'),
                'org': ('id', 'origin_id', 'name', 'created_time', 'classification_id', 'data_source_id'),
                'orgclass': ('id', 'origin_id', 'name', 'created_time', 'data_source_id'),
            },
        }

        args = [['ds', 'orgclass', 'org'], [DataSource, OrganizationClass, Organization], [True, None, None]]
        for x in range(len(args)):
            self.iterator(data=data, key=args[0][x], query=args[1][x], obj_model=data['model_maps'][args[0][x]], attr_map=data['attr_maps'][args[0][x]], phase=args[2][x])
        