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

# Type checking:
import typing
from typing import Any, Tuple

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


def fetch_graph() -> dict:
    # Generate graph base, and parse the file.
    try:
        graph = rdflib.Graph()
        graph.parse('http://finto.fi/rest/v1/jupo/data')
    except Exception as e:
        logger.error("Error while fetching JUPO Graph file: %s" % e)
    # LICENSE http://creativecommons.org/licenses/by/3.0/: https://finto.fi/jupo/fi/
    logger.info("#2: Graph parsing finished in: %s. Preparing graph..." %
                time.process_time())
    return graph


@register_importer
class JupoImporter(Importer):
    # Importer class dependant attributes:
    name = "juponew"  # Command calling name.
    supported_languages = ['fi', 'sv', 'en']  # Base file requirement.

    def iterator(self: 'events.importer.juponew.JupoImporter', data: dict, key: str, query: Any, obj_model: tuple, attr_map: tuple) -> None:
        # Main class data logic. Create DB objects & set class attributes.
        for idx, sub_key in enumerate(data[key]):
            try:
                q_obj = query()
                for count, attr in enumerate(obj_model):
                    setattr(q_obj, attr, data[key][sub_key][count])
                q_obj.save()
                setattr(self, attr_map[idx], query.objects.get(
                    id=data[key][sub_key][0]))
                keyfinder = '%s_%s' % (key, sub_key)
                for t_key in data['funcargs']['terms']:
                    for sub_t_key in data[t_key]:
                        if data[t_key][sub_t_key][-1] == keyfinder:
                            data[t_key][sub_t_key][-1] = getattr(
                                self, attr_map[idx])
            except Exception as e:
                logger.error(e)

    # Setup our class attributes & Add to DB.
    def setup(self) -> None:
        # Data mapped by models order:
        self.data = {
            # YSO, JUPO and the Public DataSource for Organizations model.
            'ds': {
                'yso': ('yso', 'Yleinen suomalainen ontologia', True),
                'jupo': ('jupo', 'Julkisen hallinnon palveluontologia', True),
                'org': ('org', 'Ulkoa tuodut organisaatiotiedot', True),
            },
            # Public organization class for all instances.
            'orgclass': {
                'sanasto': ['org:13', '13', 'Sanasto', BaseModel.now(), 'ds_org'],
            },
            # YSO & JUPO organizations for keywords.
            'org': {
                'yso': ['yso:1200', '1200', 'YSO', BaseModel.now(), 'org:13', 'ds_yso'],
                'jupo': ['jupo:1300', '1300', 'JUPO', BaseModel.now(), 'org:13', 'ds_jupo'],
            },
            # Attribute name mapping for all due to class related attributes (ex. data_source and organization are necessary).
            'attr_maps': {
                'ds': ('data_source', 'data_source_jupo', 'data_source_org'),
                # Tuples get converted to strings for single values if they don't contain , at the end
                'orgclass': ('organization_class_13',),
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

        mapped = list(map(lambda f, fto, mm, atm: [f, fto, self.data['model_maps'][mm], self.data['attr_maps'][atm]],
                      self.data['funcargs']['terms'], self.data['funcargs']['termobjs'], self.data['model_maps'], self.data['attr_maps']))

        for args in mapped:
            self.iterator(
                data=self.data, key=args[0], query=args[1], obj_model=args[2], attr_map=args[3])

        logger.info(
            "#1: Setup finished in: %s. Fetching JUPO turtle graph file..." % time.process_time())

        self.handler()

    def handler(self: 'events.importer.juponew.JupoImporter') -> None:
        # Handler function for passing the graph between functions. More organized at the cost of more function calls.
        logger.info("Here but not done yet.")
        self.graph = fetch_graph()

    # CODE DOCUMENTATION:

    # Class function: iterator()
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

    # Class function: setup()
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


        ------- Add a completely new model -------
        
        Right now we have 'ds' for DataSource, 'orgclass' for OrganizationClass and
        'org' for Organization. But you can add more underneath 'org', it has to be
        in order, and then map the given values for them to your liking, 
        and they are mapped in order by how you've added them to the 'model_maps'.
        I decided against using dictionaries within each Model because it becomes
        less organized, in this case it's nicer to keep them separate, one, for
        easy visualizaion and generally avoiding the data dictionary
        become a three level multilevel dictionary.
    '''
