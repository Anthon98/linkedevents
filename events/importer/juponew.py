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
import time
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

    '''
        Rundown of what the iterator function does:

        Iterator is our setup parser phase.
        It takes in specific data, mapped acordingly in the setup dictionary.
        You can read about that in the other comment underneath setup().

        The point of iterator is to minimize how much code you write,
        for example if we had tons of datasources, organizations and orgclasses,
        we don't always need to write in their respective model values and assign them to self,
        which could look very messy and unorganized in the long run if our dataset is huge.
        This works based on how I've organized the data dictionary.

        Funcargs term loop handles dictionary assignment for all placeholder 
        DB values. We add them by iterating through the entire data according to
        the given keyfind value, finding the recently created attribute, 
        and assigning the newly created DB object from self.
    '''

    def iterator(self, data, key, query, obj_model, attr_map) -> None:
        for idx, sub_key in enumerate(data[key]):
            try:
                q_obj = query()
                for count, attr in enumerate(obj_model):
                    setattr(q_obj, attr, data[key][sub_key][count])
                q_obj.save()
                setattr(self, attr_map[idx], query.objects.get(id=data[key][sub_key][0]))
                keyfinder = '%s_%s' % (key, sub_key)
                for t_key in data['funcargs']['terms']:
                    for sub_t_key in data[t_key]:
                        if data[t_key][sub_t_key][-1] == keyfinder:
                            data[t_key][sub_t_key][-1] = getattr(self, attr_map[idx])
            except Exception as e:
                logger.error(e)

    '''
        Rundown of how setup works:

        Setup is called in class instancing.
        
        We've defined all of our necessary data within the 'data' dictionary.
        'ds', 'orgclass' and 'org' are the current terms we use for easy iteration.

        This dictionary is made in a way that follows the model precisely.
        This model is also defined within data, so that we the program can understand
        how to iterate through it.

        We use placeholder names for the attributes that have not been instanced
        until the necessary (in this case DataSource's) model objects have been created
        into our DB. This is very easy to expand upon.

        In our situation, datasources are instanced first. We see our data in 'ds'.
        We then map the 'ds' term into terms.

        After that, orgclass is instanced, but orgclass needs our ds_org 'organization'
        datasource from the class. Fortunately I have written the iterator function,
        it takes care of these situations automatically.

        After that, organizations are made, they have the placeholder ds_yso and ds_jupo
        values. Again, iterator understands that the 'ds' means we fetch these datasources
        that have already been instanced and assigned as attributes to the class.

        You can see that the attr_maps have these 'ds', 'orgclass' and 'org' terms
        and so does models in the exact same calling order. The order matters, both
        for the function argument mapping (I generate 3 function calls without having
        to create a long unnecessary list, this is also very easily expandable) and
        the order matters for the iterator logic.

        attr_maps simply define what attribute names you want to give, the order is
        the same as how you've defined them within the respective key.

        Please note that 'data_source' and 'organization' are necessary attributes,
        and the importer expects them to exist, but in this case 'data_source' is
        mapped to yso, and 'organization' is mapped to the yso organization.

        ------------------------------------
                    HOW TO ADD:
        -------------------------------------

        ------- Add a data_source --------

        Add a new value into the 'ds' key; as an example:
        'norg': ('norg', 'New organization.', True),

        And make sure to add it to the attribute maps 'attr_maps' key:
        'ds': ('data_source', 'data_source_jupo', 'data_source_org', 'data_source_norg'),

        Simple as that!

        ------- Add an organization --------

        If you want a 'tripo' organization as an example, go add it to the 'org' key:

        Make sure to add an un-used origin ID, preferrably separating it from another used
        one by 100 or higher.

        tripo': ['tripo:1400', '1400', 'TRIPO', BaseModel.now(), 'org:13', 'ds_yso'],

        Remember to add your datasource for it like I have: 'ds_yso'. 
        It has to be an existing datasource that you've defined into 'ds'.
        Just make sure to name it according to the 'ds' key and it's sub_key value.
        Iterator function can understand to read it.

        Add 'organization_tripo' to 'attr_maps' 'org' key:
        'org': ('organization', 'organization_jupo', 'organization_tripo'),

        ------- Add an organization_class -------

        Add your new organization class to the 'orgclass' key:

        Just make sure to make the key into something that isn't used.
        'test_sanasto': ['org:14', '14', 'Test_Sanasto', BaseModel.now(), 'ds_yso'],

        And then make sure to add your attribute mapping into 'attr_maps' key:
        'orgclass': ('organization_class_13', 'organization_class_14'),
    '''
    # Setup our class attributes & Add to DB.
    def setup(self) -> None:
        # Data mapped by models order:
        data = {
            'ds': {
                'yso': ('yso', 'Yleinen suomalainen ontologia', True),
                'jupo': ('jupo', 'Julkisen hallinnon palveluontologia', True),
                'org': ('org', 'Ulkoa tuodut organisaatiotiedot', True),
            },
            'orgclass': {
                'sanasto': ['org:13', '13', 'Sanasto', BaseModel.now(), 'ds_org'],
            },
            'org': {
                'yso': ['yso:1200', '1200', 'YSO', BaseModel.now(), 'org:13', 'ds_yso'],
                'jupo': ['jupo:1300', '1300', 'JUPO', BaseModel.now(), 'org:13', 'ds_jupo'],
            },
            # Attribute name mapping for all due to class related attributes (ex. data_source and organization are necessary).
            'attr_maps': {
                'ds': ('data_source', 'data_source_jupo', 'data_source_org'),
                'orgclass': ('organization_class_13'),
                'org': ('organization', 'organization_jupo'),
            },
            # Models for easy iteration (Selected attributes):
            'model_maps': {
                'ds': ('id', 'name', 'user_editable'),
                'orgclass': ('id', 'origin_id', 'name', 'created_time', 'data_source_id'),
                'org': ('id', 'origin_id', 'name', 'created_time', 'classification_id', 'data_source_id'),
            },
            # Function arguments.
            'funcargs': {
                'terms': ('ds', 'orgclass', 'org'),
                'termobjs': (DataSource, OrganizationClass, Organization)
            },
        }

        def mkargs(f, fto, mm, atm):
            return f, fto, data['model_maps'][mm], data['attr_maps'][atm]
        
        for args in list(map(mkargs, data['funcargs']['terms'], data['funcargs']['termobjs'], data['model_maps'], data['attr_maps'])):
            self.iterator(data=data, key=args[0], query=args[1], obj_model=args[2], attr_map=args[3])

        logger.info("Done. %s" % time.process_time())
