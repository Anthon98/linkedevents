# -*- coding: utf-8 -*-

# Dependencies.

# RDFLIB:
import rdflib
from rdflib import RDF, URIRef
from rdflib.namespace import DCTERMS, OWL, SKOS

# Logging:
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
from typing import TYPE_CHECKING, Any, Tuple, List

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

    def process_graph(self: 'events.importer.juponew.JupoImporter', graph: dict) -> Tuple[dict, List[Any]]:
        processed = {}
        deprecated = []
        specifications = {
            # YSO has two types we want based on the metatag. ex: yso-meta1:Concept & yso-meta:Individual
            'yso': {
                'types': ('Concept', 'Individual'),
                'meta': ('yso-meta',),
            },
            # JUPO on the other hand only has Concept. ex: jupometa:Concept
            'jupo': {
                'types': ('Concept',),
                'meta': ('jupo-meta',),
            },
        }
        # Loop through all Concepts. Includes deprecated and regular.
        for subj_uriRef in graph.subjects(predicate=None, object=SKOS.Concept):
            subj_type, subj_id = subj_uriRef.split('/')[-2:]
            formatted_onto = "%s:%s" % (subj_type, subj_id)
            if subj_type in specifications.keys():
                valid = None
                sub_skos = {
                    'altLabel': {'fi': None, 'sv': None, 'en': None},
                    'prefLabel': {'fi': None, 'sv': None, 'en': None},
                    'broader': [],
                    'narrower': [],
                }
                for types in specifications[subj_type]['types']:
                    for meta in specifications[subj_type]['meta']:
                        mkuriref = rdflib.term.URIRef(
                            'http://www.yso.fi/onto/%s/%s' % (meta, types))
                        if (subj_uriRef, None, mkuriref) in graph:
                            valid = True
                if valid:
                    # Gather labels: altLabel, prefLabel, broader, narrower.
                    for label, v in sub_skos.items():
                        for obj in graph.objects(subject=subj_uriRef, predicate=SKOS[label]):
                            if isinstance(v, dict):
                                v.update(
                                    dict({str(obj.language): str(obj.value)}))
                            else:
                                v.append(obj)
                    processed.update(dict({formatted_onto: {
                        'altLabel': sub_skos['altLabel'],
                        'prefLabel': sub_skos['prefLabel'],
                        'broader': sub_skos['broader'],
                        'narrower': sub_skos['narrower'],
                        'type': subj_type, 'id': subj_id
                    }}))
                else:
                    if (subj_uriRef, OWL.deprecated, None) in graph:
                        isReplacedBy = None
                        for _, _, object in graph.triples((subj_uriRef, DCTERMS.isReplacedBy, None)):
                            st, sid = object.split('/')[-2:]
                            formatted_obj = "%s:%s" % (st, sid)
                            isReplacedBy = formatted_obj
                        deprecated.append([formatted_onto, isReplacedBy])
        return processed, deprecated

    def save_alt_keywords(self: 'events.importer.juponew.JupoImporter', processed: dict) -> None:
        for k in processed:
            for lang in processed[k]['altLabel']:
                if processed[k]['altLabel'][lang]:
                    try:
                        # Check duplicates:
                        alt_label_exists = KeywordLabel.objects.filter(
                            name=processed[k]['altLabel'][lang]).exists()
                        if not alt_label_exists:
                            language = Language.objects.get(id=lang)
                            label_object = KeywordLabel(
                                name=processed[k]['altLabel'][lang], language=language)
                            label_object.save()
                    except Exception as e:
                        logger.error(e)

    def save_keywords(self: 'events.importer.juponew.JupoImporter', processed: dict) -> None:
        for k, v in processed.items():
            try:
                if v['type'] == 'jupo':
                    keyword = Keyword(data_source=getattr(
                        self, 'data_source_jupo'))
                else:
                    keyword = Keyword(data_source=getattr(self, 'data_source'))
                keyword.id = k
                keyword.created_time = BaseModel.now()
                for lang, lang_val in v['prefLabel'].items():
                    langformat = 'name_%s' % lang
                    setattr(keyword, langformat, lang_val)
                keyword.broader = v['broader']
                keyword.narrower = v['narrower']
                keyword.save()
                alts = []
                # Link ManyToMany relation alt label values.
                for alt_lang in v['altLabel']:
                    alt_obj = v['altLabel'][alt_lang]
                    cur_obj = None
                    try:
                        cur_obj = KeywordLabel.objects.filter(
                            name=alt_obj, language_id=alt_lang).first()
                    except Exception as e:
                        logger.error(e)
                    if cur_obj:
                        alts.append(cur_obj)
                if alts:
                    keyword.alt_labels.add(*alts)
                    keyword.save()
            except Exception as e:
                logger.error(e)

    def mark_deprecated(self: 'events.importer.juponew.JupoImporter', deprecated: dict) -> None:
        for value in deprecated:
            onto = value[0]
            replacement = value[1]
            try:
                keyword = Keyword.objects.get(id=onto)
                if keyword:
                    # try:
                    #    replaced_keyword = Keyword.objects.get(id=replacement)
                    #    if replaced_keyword:
                    #        keyword.replaced_by_id = replaced_keyword
                    # except:
                    #    logger.warn(
                    #        'Could not find replacement key for %s' % onto)
                    #    continue
                    keyword.deprecated = True
                    keyword.created_time = BaseModel.now()
                    keyword.save()
                    logger.info("Marked deprecated: %s" % value[0])
            except:
                pass

    # Setup our class attributes & Add to DB.

    def setup(self) -> None:
        # Data mapped by models order:
        self.data = {
            # YSO, JUPO and the Public DataSource for Organizations model.
            'ds': {
                'yso': ('yso', 'TEST Yleinen suomalainen ontologia', True),
                'jupo': ('jupo', 'TEST Julkisen hallinnon palveluontologia', True),
                'org': ('org', 'TEST Ulkoa tuodut organisaatiotiedot', True),
            },
            # Public organization class for all instances.
            'orgclass': {
                'sanasto': ['org:13', '13', 'SanastoTEST', BaseModel.now(), 'ds_org'],
            },
            # YSO & JUPO organizations for keywords.
            'org': {
                'yso': ['yso:1200', '1200', 'YSOTEST', BaseModel.now(), 'org:13', 'ds_yso'],
                'jupo': ['jupo:1300', '1300', 'JUPOTEST', BaseModel.now(), 'org:13', 'ds_jupo'],
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
        self.graph = fetch_graph()
        logger.info("#2: Graph parsing finished in: %s. Preparing graph..." %
                    time.process_time())
        self.processed, self.deprecated = self.process_graph(graph=self.graph)
        logger.info("#3: Graph processing finished in: %s..." %
                    time.process_time())
        self.save_alt_keywords(processed=self.processed)
        logger.info("#4: Alt keyword saving finished in: %s..." %
                    time.process_time())
        self.save_keywords(processed=self.processed)
        logger.info("#5: Saved non-deprecated keywords in: %s..." %
                    time.process_time())
        self.mark_deprecated(self.deprecated)
        logger.info("#6: Handled deprecated keywords in: %s..." %
                    time.process_time())

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
