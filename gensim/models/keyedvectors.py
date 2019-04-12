#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Author: Shiva Manne <manneshiva@gmail.com>
# Copyright (C) 2018 RaRe Technologies s.r.o.
# Licensed under the GNU LGPL v2.1 - http://www.gnu.org/licenses/lgpl.html

"""This module implements word vectors and their similarity look-ups.

Since trained word vectors are independent from the way they were trained (:class:`~gensim.models.word2vec.Word2Vec`,
:class:`~gensim.models.fasttext.FastText`, :class:`~gensim.models.wrappers.wordrank.WordRank`,
:class:`~gensim.models.wrappers.varembed.VarEmbed` etc), they can be represented by a standalone structure,
as implemented in this module.

The structure is called "KeyedVectors" and is essentially a mapping between *entities*
and *vectors*. Each entity is identified by its string id, so this is a mapping between {str => 1D numpy array}.

The entity typically corresponds to a word (so the mapping maps words to 1D vectors),
but for some models, the key can also correspond to a document, a graph node etc. To generalize
over different use-cases, this module calls the keys **entities**. Each entity is
always represented by its string id, no matter whether the entity is a word, a document or a graph node.

Why use KeyedVectors instead of a full model?
=============================================

+---------------------------+--------------+------------+-------------------------------------------------------------+
|        capability         | KeyedVectors | full model |                               note                          |
+---------------------------+--------------+------------+-------------------------------------------------------------+
| continue training vectors | ❌           | ✅         | You need the full model to train or update vectors.         |
+---------------------------+--------------+------------+-------------------------------------------------------------+
| smaller objects           | ✅           | ❌         | KeyedVectors are smaller and need less RAM, because they    |
|                           |              |            | don't need to store the model state that enables training.  |
+---------------------------+--------------+------------+-------------------------------------------------------------+
| save/load from native     |              |            | Vectors exported by the Facebook and Google tools           |
| fasttext/word2vec format  | ✅           | ❌         | do not support further training, but you can still load     |
|                           |              |            | them into KeyedVectors.                                     |
+---------------------------+--------------+------------+-------------------------------------------------------------+
| append new vectors        | ✅           | ✅         | Add new entity-vector entries to the mapping dynamically.   |
+---------------------------+--------------+------------+-------------------------------------------------------------+
| concurrency               | ✅           | ✅         | Thread-safe, allows concurrent vector queries.              |
+---------------------------+--------------+------------+-------------------------------------------------------------+
| shared RAM                | ✅           | ✅         | Multiple processes can re-use the same data, keeping only   |
|                           |              |            | a single copy in RAM using                                  |
|                           |              |            | `mmap <https://en.wikipedia.org/wiki/Mmap>`_.               |
+---------------------------+--------------+------------+-------------------------------------------------------------+
| fast load                 | ✅           | ✅         | Supports `mmap <https://en.wikipedia.org/wiki/Mmap>`_       |
|                           |              |            | to load data from disk instantaneously.                     |
+---------------------------+--------------+------------+-------------------------------------------------------------+

TL;DR: the main difference is that KeyedVectors do not support further training.
On the other hand, by shedding the internal data structures necessary for training, KeyedVectors offer a smaller RAM
footprint and a simpler interface.

How to obtain word vectors?
===========================

Train a full model, then access its `model.wv` property, which holds the standalone keyed vectors.
For example, using the Word2Vec algorithm to train the vectors

.. sourcecode:: pycon

    >>> from gensim.test.utils import common_texts
    >>> from gensim.models import Word2Vec
    >>>
    >>> model = Word2Vec(common_texts, size=100, window=5, min_count=1, workers=4)
    >>> word_vectors = model.wv

Persist the word vectors to disk with

.. sourcecode:: pycon

    >>> from gensim.test.utils import get_tmpfile
    >>> from gensim.models import KeyedVectors
    >>>
    >>> fname = get_tmpfile("vectors.kv")
    >>> word_vectors.save(fname)
    >>> word_vectors = KeyedVectors.load(fname, mmap='r')

The vectors can also be instantiated from an existing file on disk
in the original Google's word2vec C format as a KeyedVectors instance

.. sourcecode:: pycon

    >>> from gensim.test.utils import datapath
    >>>
    >>> wv_from_text = KeyedVectors.load_word2vec_format(datapath('word2vec_pre_kv_c'), binary=False)  # C text format
    >>> wv_from_bin = KeyedVectors.load_word2vec_format(datapath("euclidean_vectors.bin"), binary=True)  # C bin format

What can I do with word vectors?
================================

You can perform various syntactic/semantic NLP word tasks with the trained vectors.
Some of them are already built-in

.. sourcecode:: pycon

    >>> import gensim.downloader as api
    >>>
    >>> word_vectors = api.load("glove-wiki-gigaword-100")  # load pre-trained word-vectors from gensim-data
    >>>
    >>> result = word_vectors.most_similar(positive=['woman', 'king'], negative=['man'])
    >>> print("{}: {:.4f}".format(*result[0]))
    queen: 0.7699
    >>>
    >>> result = word_vectors.most_similar_cosmul(positive=['woman', 'king'], negative=['man'])
    >>> print("{}: {:.4f}".format(*result[0]))
    queen: 0.8965
    >>>
    >>> print(word_vectors.doesnt_match("breakfast cereal dinner lunch".split()))
    cereal
    >>>
    >>> similarity = word_vectors.similarity('woman', 'man')
    >>> similarity > 0.8
    True
    >>>
    >>> result = word_vectors.similar_by_word("cat")
    >>> print("{}: {:.4f}".format(*result[0]))
    dog: 0.8798
    >>>
    >>> sentence_obama = 'Obama speaks to the media in Illinois'.lower().split()
    >>> sentence_president = 'The president greets the press in Chicago'.lower().split()
    >>>
    >>> similarity = word_vectors.wmdistance(sentence_obama, sentence_president)
    >>> print("{:.4f}".format(similarity))
    3.4893
    >>>
    >>> distance = word_vectors.distance("media", "media")
    >>> print("{:.1f}".format(distance))
    0.0
    >>>
    >>> sim = word_vectors.n_similarity(['sushi', 'shop'], ['japanese', 'restaurant'])
    >>> print("{:.4f}".format(sim))
    0.7067
    >>>
    >>> vector = word_vectors['computer']  # numpy vector of a word
    >>> vector.shape
    (100,)
    >>>
    >>> vector = word_vectors.wv.word_vec('office', use_norm=True)
    >>> vector.shape
    (100,)

Correlation with human opinion on word similarity

.. sourcecode:: pycon

    >>> from gensim.test.utils import datapath
    >>>
    >>> similarities = model.wv.evaluate_word_pairs(datapath('wordsim353.tsv'))

And on word analogies

.. sourcecode:: pycon

    >>> analogy_scores = model.wv.evaluate_word_analogies(datapath('questions-words.txt'))

and so on.

"""

from __future__ import division  # py3 "true division"

from itertools import chain
import logging

try:
    from queue import Queue, Empty
except ImportError:
    from Queue import Queue, Empty  # noqa:F401

from numpy import dot, float32 as REAL, memmap as np_memmap, \
    double, array, zeros, vstack, sqrt, newaxis, integer, \
    ndarray, sum as np_sum, prod, argmax
import numpy as np

from gensim import utils, matutils  # utility fnc for pickling, common scipy operations etc
from gensim.corpora.dictionary import Dictionary
from six import string_types, integer_types
from six.moves import zip, range
from scipy import stats
from gensim.utils import deprecated
from gensim.models.utils_any2vec import (
    _save_word2vec_format,
    _load_word2vec_format,
    ft_ngram_hashes,
)
from gensim.similarities.termsim import TermSimilarityIndex, SparseTermSimilarityMatrix

logger = logging.getLogger(__name__)


class Vocab(object):
    """A single vocabulary item, used internally for collecting per-word frequency/sampling info,
    and for constructing binary trees (incl. both word leaves and inner nodes).

    """
    def __init__(self, **kwargs):
        self.count = 0
        self.__dict__.update(kwargs)

    def __lt__(self, other):  # used for sorting in a priority queue
        return self.count < other.count

    def __str__(self):
        vals = ['%s:%r' % (key, self.__dict__[key]) for key in sorted(self.__dict__) if not key.startswith('_')]
        return "%s(%s)" % (self.__class__.__name__, ', '.join(vals))


class BaseKeyedVectors(utils.SaveLoad):
    """Abstract base class / interface for various types of word vectors."""
    def __init__(self, vector_size):
        self.vectors = zeros((0, vector_size))
        self.vocab = {}
        self.vector_size = vector_size
        self.index2entity = []

    def save(self, fname_or_handle, **kwargs):
        super(BaseKeyedVectors, self).save(fname_or_handle, **kwargs)

    @classmethod
    def load(cls, fname_or_handle, **kwargs):
        return super(BaseKeyedVectors, cls).load(fname_or_handle, **kwargs)

    def similarity(self, entity1, entity2):
        """Compute cosine similarity between two entities, specified by their string id."""
        raise NotImplementedError()

    def most_similar(self, **kwargs):
        """Find the top-N most similar entities.
        Possibly have `positive` and `negative` list of entities in `**kwargs`.

        """
        return NotImplementedError()

    def distance(self, entity1, entity2):
        """Compute distance between vectors of two input entities, specified by their string id."""
        raise NotImplementedError()

    def distances(self, entity1, other_entities=()):
        """Compute distances from a given entity (its string id) to all entities in `other_entity`.
        If `other_entities` is empty, return the distance between `entity1` and all entities in vocab.

        """
        raise NotImplementedError()

    def get_vector(self, entity):
        """Get the entity's representations in vector space, as a 1D numpy array.

        Parameters
        ----------
        entity : str
            Identifier of the entity to return the vector for.

        Returns
        -------
        numpy.ndarray
            Vector for the specified entity.

        Raises
        ------
        KeyError
            If the given entity identifier doesn't exist.

        """
        if entity in self.vocab:
            result = self.vectors[self.vocab[entity].index]
            result.setflags(write=False)
            return result
        else:
            raise KeyError("'%s' not in vocabulary" % entity)

    def add(self, entities, weights, replace=False):
        """Append entities and theirs vectors in a manual way.
        If some entity is already in the vocabulary, the old vector is kept unless `replace` flag is True.

        Parameters
        ----------
        entities : list of str
            Entities specified by string ids.
        weights: {list of numpy.ndarray, numpy.ndarray}
            List of 1D np.array vectors or a 2D np.array of vectors.
        replace: bool, optional
            Flag indicating whether to replace vectors for entities which already exist in the vocabulary,
            if True - replace vectors, otherwise - keep old vectors.

        """
        if isinstance(entities, string_types):
            entities = [entities]
            weights = np.array(weights).reshape(1, -1)
        elif isinstance(weights, list):
            weights = np.array(weights)

        in_vocab_mask = np.zeros(len(entities), dtype=np.bool)
        for idx, entity in enumerate(entities):
            if entity in self.vocab:
                in_vocab_mask[idx] = True

        # add new entities to the vocab
        for idx in np.nonzero(~in_vocab_mask)[0]:
            entity = entities[idx]
            self.vocab[entity] = Vocab(index=len(self.vocab), count=1)
            self.index2entity.append(entity)

        # add vectors for new entities
        self.vectors = vstack((self.vectors, weights[~in_vocab_mask]))

        # change vectors for in_vocab entities if `replace` flag is specified
        if replace:
            in_vocab_idxs = [self.vocab[entities[idx]].index for idx in np.nonzero(in_vocab_mask)[0]]
            self.vectors[in_vocab_idxs] = weights[in_vocab_mask]

    def __setitem__(self, entities, weights):
        """Add entities and theirs vectors in a manual way.
        If some entity is already in the vocabulary, old vector is replaced with the new one.
        This method is alias for :meth:`~gensim.models.keyedvectors.BaseKeyedVectors.add` with `replace=True`.

        Parameters
        ----------
        entities : {str, list of str}
            Entities specified by their string ids.
        weights: {list of numpy.ndarray, numpy.ndarray}
            List of 1D np.array vectors or 2D np.array of vectors.

        """
        if not isinstance(entities, list):
            entities = [entities]
            weights = weights.reshape(1, -1)

        self.add(entities, weights, replace=True)

    def __getitem__(self, entities):
        """Get vector representation of `entities`.

        Parameters
        ----------
        entities : {str, list of str}
            Input entity/entities.

        Returns
        -------
        numpy.ndarray
            Vector representation for `entities` (1D if `entities` is string, otherwise - 2D).

        """
        if isinstance(entities, string_types):
            # allow calls like trained_model['office'], as a shorthand for trained_model[['office']]
            return self.get_vector(entities)

        return vstack([self.get_vector(entity) for entity in entities])

    def __contains__(self, entity):
        return entity in self.vocab

    def most_similar_to_given(self, entity1, entities_list):
        """Get the `entity` from `entities_list` most similar to `entity1`."""
        return entities_list[argmax([self.similarity(entity1, entity) for entity in entities_list])]

    def closer_than(self, entity1, entity2):
        """Get all entities that are closer to `entity1` than `entity2` is to `entity1`."""
        all_distances = self.distances(entity1)
        e1_index = self.vocab[entity1].index
        e2_index = self.vocab[entity2].index
        closer_node_indices = np.where(all_distances < all_distances[e2_index])[0]
        return [self.index2entity[index] for index in closer_node_indices if index != e1_index]

    def rank(self, entity1, entity2):
        """Rank of the distance of `entity2` from `entity1`, in relation to distances of all entities from `entity1`."""
        return len(self.closer_than(entity1, entity2)) + 1


class WordEmbeddingsKeyedVectors(BaseKeyedVectors):
    """Class containing common methods for operations over word vectors."""
    def __init__(self, vector_size):
        super(WordEmbeddingsKeyedVectors, self).__init__(vector_size=vector_size)
        self.vectors_norm = None
        self.index2word = []

    @property
    @deprecated("Attribute will be removed in 4.0.0, use self instead")
    def wv(self):
        return self

    @property
    def index2entity(self):
        return self.index2word

    @index2entity.setter
    def index2entity(self, value):
        self.index2word = value

    @property
    @deprecated("Attribute will be removed in 4.0.0, use self.vectors instead")
    def syn0(self):
        return self.vectors

    @syn0.setter
    @deprecated("Attribute will be removed in 4.0.0, use self.vectors instead")
    def syn0(self, value):
        self.vectors = value

    @property
    @deprecated("Attribute will be removed in 4.0.0, use self.vectors_norm instead")
    def syn0norm(self):
        return self.vectors_norm

    @syn0norm.setter
    @deprecated("Attribute will be removed in 4.0.0, use self.vectors_norm instead")
    def syn0norm(self, value):
        self.vectors_norm = value

    def __contains__(self, word):
        return word in self.vocab

    def save(self, *args, **kwargs):
        """Save KeyedVectors.

        Parameters
        ----------
        fname : str
            Path to the output file.

        See Also
        --------
        :meth:`~gensim.models.keyedvectors.WordEmbeddingsKeyedVectors.load`
            Load saved model.

        """
        # don't bother storing the cached normalized vectors
        kwargs['ignore'] = kwargs.get('ignore', ['vectors_norm'])
        super(WordEmbeddingsKeyedVectors, self).save(*args, **kwargs)

    def word_vec(self, word, use_norm=False):
        """Get `word` representations in vector space, as a 1D numpy array.

        Parameters
        ----------
        word : str
            Input word
        use_norm : bool, optional
            If True - resulting vector will be L2-normalized (unit euclidean length).

        Returns
        -------
        numpy.ndarray
            Vector representation of `word`.

        Raises
        ------
        KeyError
            If word not in vocabulary.

        """
        if word in self.vocab:
            if use_norm:
                result = self.vectors_norm[self.vocab[word].index]
            else:
                result = self.vectors[self.vocab[word].index]

            result.setflags(write=False)
            return result
        else:
            raise KeyError("word '%s' not in vocabulary" % word)

    def get_vector(self, word):
        return self.word_vec(word)

    def words_closer_than(self, w1, w2):
        """Get all words that are closer to `w1` than `w2` is to `w1`.

        Parameters
        ----------
        w1 : str
            Input word.
        w2 : str
            Input word.

        Returns
        -------
        list (str)
            List of words that are closer to `w1` than `w2` is to `w1`.

        """
        return super(WordEmbeddingsKeyedVectors, self).closer_than(w1, w2)

    def most_similar(self, positive=None, negative=None, topn=10, restrict_vocab=None, indexer=None):
        """Find the top-N most similar words.
        Positive words contribute positively towards the similarity, negative words negatively.

        This method computes cosine similarity between a simple mean of the projection
        weight vectors of the given words and the vectors for each word in the model.
        The method corresponds to the `word-analogy` and `distance` scripts in the original
        word2vec implementation.

        Parameters
        ----------
        positive : list of str, optional
            List of words that contribute positively.
        negative : list of str, optional
            List of words that contribute negatively.
        topn : int, optional
            Number of top-N similar words to return.
        restrict_vocab : int, optional
            Optional integer which limits the range of vectors which
            are searched for most-similar values. For example, restrict_vocab=10000 would
            only check the first 10000 word vectors in the vocabulary order. (This may be
            meaningful if you've sorted the vocabulary by descending frequency.)

        Returns
        -------
        list of (str, float)
            Sequence of (word, similarity).

        """
        if topn is not None and topn < 1:
            return []

        if positive is None:
            positive = []
        if negative is None:
            negative = []

        self.init_sims()

        if isinstance(positive, string_types) and not negative:
            # allow calls like most_similar('dog'), as a shorthand for most_similar(['dog'])
            positive = [positive]

        # add weights for each word, if not already present; default to 1.0 for positive and -1.0 for negative words
        positive = [
            (word, 1.0) if isinstance(word, string_types + (ndarray,)) else word
            for word in positive
        ]
        negative = [
            (word, -1.0) if isinstance(word, string_types + (ndarray,)) else word
            for word in negative
        ]

        # compute the weighted average of all words
        all_words, mean = set(), []
        for word, weight in positive + negative:
            if isinstance(word, ndarray):
                mean.append(weight * word)
            else:
                mean.append(weight * self.word_vec(word, use_norm=True))
                if word in self.vocab:
                    all_words.add(self.vocab[word].index)
        if not mean:
            raise ValueError("cannot compute similarity with no input")
        mean = matutils.unitvec(array(mean).mean(axis=0)).astype(REAL)

        if indexer is not None:
            return indexer.most_similar(mean, topn)

        limited = self.vectors_norm if restrict_vocab is None else self.vectors_norm[:restrict_vocab]
        dists = dot(limited, mean)
        if topn is None:
            return dists
        best = matutils.argsort(dists, topn=topn + len(all_words), reverse=True)
        # ignore (don't return) words from the input
        result = [(self.index2word[sim], float(dists[sim])) for sim in best if sim not in all_words]
        return result[:topn]

    def similar_by_word(self, word, topn=10, restrict_vocab=None):
        """Find the top-N most similar words.

        Parameters
        ----------
        word : str
            Word
        topn : {int, False}, optional
            Number of top-N similar words to return. If topn is False, similar_by_word returns
            the vector of similarity scores.
        restrict_vocab : int, optional
            Optional integer which limits the range of vectors which
            are searched for most-similar values. For example, restrict_vocab=10000 would
            only check the first 10000 word vectors in the vocabulary order. (This may be
            meaningful if you've sorted the vocabulary by descending frequency.)

        Returns
        -------
        list of (str, float)
            Sequence of (word, similarity).

        """
        return self.most_similar(positive=[word], topn=topn, restrict_vocab=restrict_vocab)

    def similar_by_vector(self, vector, topn=10, restrict_vocab=None):
        """Find the top-N most similar words by vector.

        Parameters
        ----------
        vector : numpy.array
            Vector from which similarities are to be computed.
        topn : {int, False}, optional
            Number of top-N similar words to return. If topn is False, similar_by_vector returns
            the vector of similarity scores.
        restrict_vocab : int, optional
            Optional integer which limits the range of vectors which
            are searched for most-similar values. For example, restrict_vocab=10000 would
            only check the first 10000 word vectors in the vocabulary order. (This may be
            meaningful if you've sorted the vocabulary by descending frequency.)

        Returns
        -------
        list of (str, float)
            Sequence of (word, similarity).

        """
        return self.most_similar(positive=[vector], topn=topn, restrict_vocab=restrict_vocab)
        
    def visualize(self, words, depth=10, edge=False, font="Georgia"):
        """Draw D3.js-based visualization in HTML code for the top-N most similar words of the target.
        Parameters
        ----------
        word : str or list
            Word
        depth : {int}, optional
            Number of top-N similar words to return. 
        edge: bool, optional
            Optional boolean which tells whether to render edges according to similarity strength.
        font: str, optional
            Optional boolean for font family to use in HTML, default is Georgia which is cross-platform one.
        Returns
        -------
        str
            HTML code for visualization of similarity relations of (word).
        """
        html = """
        <!DOCTYPE html><html><head><meta charset="utf-8"><meta http-equiv="X-UA-Compatible" content="IE=edge"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="wordplaceholder"><meta name="author" content="Alyaxey Yaskevich"><title>wordplaceholder</title><script>!function(){function n(n){return n&&(n.ownerDocument||n.document||n).documentElement}function t(n){return n&&(n.ownerDocument&&n.ownerDocument.defaultView||n.document&&n||n.defaultView)}function e(n,t){return t>n?-1:n>t?1:n>=t?0:NaN}function r(n){return null===n?NaN:+n}function i(n){return!isNaN(n)}function u(n){return{left:function(t,e,r,i){for(arguments.length<3&&(r=0),arguments.length<4&&(i=t.length);i>r;){var u=r+i>>>1;n(t[u],e)<0?r=u+1:i=u}return r},right:function(t,e,r,i){for(arguments.length<3&&(r=0),arguments.length<4&&(i=t.length);i>r;){var u=r+i>>>1;n(t[u],e)>0?i=u:r=u+1}return r}}}function o(n){return n.length}function a(n,t){for(var e in t)Object.defineProperty(n.prototype,e,{value:t[e],enumerable:!1})}function c(){this._=Object.create(null)}function l(n){return(n+="")===au||n[0]===cu?cu+n:n}function f(n){return(n+="")[0]===cu?n.slice(1):n}function s(n){return l(n)in this._}function h(n){return(n=l(n))in this._&&delete this._[n]}function p(){var n=[];for(var t in this._)n.push(f(t));return n}function g(){var n=0;for(var t in this._)++n;return n}function v(){for(var n in this._)return!1;return!0}function d(){this._=Object.create(null)}function y(n){return n}function m(n,t,e){return function(){var r=e.apply(t,arguments);return r===t?n:r}}function M(n,t){if(t in n)return t;t=t.charAt(0).toUpperCase()+t.slice(1);for(var e=0,r=lu.length;r>e;++e){var i=lu[e]+t;if(i in n)return i}}function x(){}function b(){}function _(n){function t(){for(var t,r=e,i=-1,u=r.length;++i<u;)(t=r[i].on)&&t.apply(this,arguments);return n}var e=[],r=new c;return t.on=function(t,i){var u,o=r.get(t);return arguments.length<2?o&&o.on:(o&&(o.on=null,e=e.slice(0,u=e.indexOf(o)).concat(e.slice(u+1)),r.remove(t)),i&&e.push(r.set(t,{on:i})),n)},t}function w(){Ji.event.preventDefault()}function S(){for(var n,t=Ji.event;n=t.sourceEvent;)t=n;return t}function k(n){for(var t=new b,e=0,r=arguments.length;++e<r;)t[arguments[e]]=_(t);return t.of=function(e,r){return function(i){try{var u=i.sourceEvent=Ji.event;i.target=n,Ji.event=i,t[i.type].apply(e,r)}finally{Ji.event=u}}},t}function N(n){return su(n,vu),n}function E(n){return"function"==typeof n?n:function(){return hu(n,this)}}function A(n){return"function"==typeof n?n:function(){return pu(n,this)}}function C(n,t){return n=Ji.ns.qualify(n),null==t?n.local?function(){this.removeAttributeNS(n.space,n.local)}:function(){this.removeAttribute(n)}:"function"==typeof t?n.local?function(){var e=t.apply(this,arguments);null==e?this.removeAttributeNS(n.space,n.local):this.setAttributeNS(n.space,n.local,e)}:function(){var e=t.apply(this,arguments);null==e?this.removeAttribute(n):this.setAttribute(n,e)}:n.local?function(){this.setAttributeNS(n.space,n.local,t)}:function(){this.setAttribute(n,t)}}function z(n){return n.trim().replace(/\s+/g," ")}function q(n){return new RegExp("(?:^|\\s+)"+Ji.requote(n)+"(?:\\s+|$)","g")}function L(n){return(n+"").trim().split(/^|\s+/)}function T(n,t){var e=(n=L(n).map(R)).length;return"function"==typeof t?function(){for(var r=-1,i=t.apply(this,arguments);++r<e;)n[r](this,i)}:function(){for(var r=-1;++r<e;)n[r](this,t)}}function R(n){var t=q(n);return function(e,r){if(i=e.classList)return r?i.add(n):i.remove(n);var i=e.getAttribute("class")||"";r?(t.lastIndex=0,t.test(i)||e.setAttribute("class",z(i+" "+n))):e.setAttribute("class",z(i.replace(t," ")))}}function D(n,t,e){return null==t?function(){this.style.removeProperty(n)}:"function"==typeof t?function(){var r=t.apply(this,arguments);null==r?this.style.removeProperty(n):this.style.setProperty(n,r,e)}:function(){this.style.setProperty(n,t,e)}}function P(n,t){return null==t?function(){delete this[n]}:"function"==typeof t?function(){var e=t.apply(this,arguments);null==e?delete this[n]:this[n]=e}:function(){this[n]=t}}function U(n){return"function"==typeof n?n:(n=Ji.ns.qualify(n)).local?function(){return this.ownerDocument.createElementNS(n.space,n.local)}:function(){var t=this.ownerDocument,e=this.namespaceURI;return e?t.createElementNS(e,n):t.createElement(n)}}function j(){var n=this.parentNode;n&&n.removeChild(this)}function F(n){return{__data__:n}}function H(n){return function(){return gu(this,n)}}function O(n){return arguments.length||(n=e),function(t,e){return t&&e?n(t.__data__,e.__data__):!t-!e}}function I(n,t){for(var e=0,r=n.length;r>e;e++)for(var i,u=n[e],o=0,a=u.length;a>o;o++)(i=u[o])&&t(i,o,e);return n}function Y(n){return su(n,yu),n}function Z(n,t,e){function r(){var t=this[i];t&&(this.removeEventListener(n,t,t.$),delete this[i])}var i="__on"+n,u=n.indexOf("."),o=V;u>0&&(n=n.slice(0,u));var a=mu.get(n);return a&&(n=a,o=X),u?t?function(){var u=o(t,Ki(arguments));r.call(this),this.addEventListener(n,this[i]=u,u.$=e),u._=t}:r:t?x:function(){var t,e=new RegExp("^__on([^.]+)"+Ji.requote(n)+"$");for(var r in this)if(t=r.match(e)){var i=this[r];this.removeEventListener(t[1],i,i.$),delete this[r]}}}function V(n,t){return function(e){var r=Ji.event;Ji.event=e,t[0]=this.__data__;try{n.apply(this,t)}finally{Ji.event=r}}}function X(n,t){var e=V(n,t);return function(n){var t=this,r=n.relatedTarget;r&&(r===t||8&r.compareDocumentPosition(t))||e.call(t,n)}}function $(e){var r=".dragsuppress-"+ ++xu,i="click"+r,u=Ji.select(t(e)).on("touchmove"+r,w).on("dragstart"+r,w).on("selectstart"+r,w);if(null==Mu&&(Mu=!("onselectstart"in e)&&M(e.style,"userSelect")),Mu){var o=n(e).style,a=o[Mu];o[Mu]="none"}return function(n){if(u.on(r,null),Mu&&(o[Mu]=a),n){var t=function(){u.on(i,null)};u.on(i,function(){w(),t()},!0),setTimeout(t,0)}}}function B(n,e){e.changedTouches&&(e=e.changedTouches[0]);var r=n.ownerSVGElement||n;if(r.createSVGPoint){var i=r.createSVGPoint();if(0>bu){var u=t(n);if(u.scrollX||u.scrollY){var o=(r=Ji.select("body").append("svg").style({position:"absolute",top:0,left:0,margin:0,padding:0,border:"none"},"important"))[0][0].getScreenCTM();bu=!(o.f||o.e),r.remove()}}return bu?(i.x=e.pageX,i.y=e.pageY):(i.x=e.clientX,i.y=e.clientY),[(i=i.matrixTransform(n.getScreenCTM().inverse())).x,i.y]}var a=n.getBoundingClientRect();return[e.clientX-a.left-n.clientLeft,e.clientY-a.top-n.clientTop]}function W(){return Ji.event.changedTouches[0].identifier}function J(n){return n>0?1:0>n?-1:0}function G(n,t,e){return(t[0]-n[0])*(e[1]-n[1])-(t[1]-n[1])*(e[0]-n[0])}function K(n){return n>1?0:-1>n?Su:Math.acos(n)}function Q(n){return n>1?Eu:-1>n?-Eu:Math.asin(n)}function nn(n){return((n=Math.exp(n))+1/n)/2}function tn(n){return(n=Math.sin(n/2))*n}function en(){}function rn(n,t,e){return this instanceof rn?(this.h=+n,this.s=+t,void(this.l=+e)):arguments.length<2?n instanceof rn?new rn(n.h,n.s,n.l):mn(""+n,Mn,rn):new rn(n,t,e)}function un(n,t,e){function r(n){return Math.round(255*function(n){return n>360?n-=360:0>n&&(n+=360),60>n?i+(u-i)*n/60:180>n?u:240>n?i+(u-i)*(240-n)/60:i}(n))}var i,u;return n=isNaN(n)?0:(n%=360)<0?n+360:n,t=isNaN(t)?0:0>t?0:t>1?1:t,i=2*(e=0>e?0:e>1?1:e)-(u=.5>=e?e*(1+t):e+t-e*t),new gn(r(n+120),r(n),r(n-120))}function on(n,t,e){return this instanceof on?(this.h=+n,this.c=+t,void(this.l=+e)):arguments.length<2?n instanceof on?new on(n.h,n.c,n.l):fn(n instanceof cn?n.l:(n=xn((n=Ji.rgb(n)).r,n.g,n.b)).l,n.a,n.b):new on(n,t,e)}function an(n,t,e){return isNaN(n)&&(n=0),isNaN(t)&&(t=0),new cn(e,Math.cos(n*=Au)*t,Math.sin(n)*t)}function cn(n,t,e){return this instanceof cn?(this.l=+n,this.a=+t,void(this.b=+e)):arguments.length<2?n instanceof cn?new cn(n.l,n.a,n.b):n instanceof on?an(n.h,n.c,n.l):xn((n=gn(n)).r,n.g,n.b):new cn(n,t,e)}function ln(n,t,e){var r=(n+16)/116,i=r+t/500,u=r-e/200;return new gn(pn(3.2404542*(i=sn(i)*ju)-1.5371385*(r=sn(r)*Fu)-.4985314*(u=sn(u)*Hu)),pn(-.969266*i+1.8760108*r+.041556*u),pn(.0556434*i-.2040259*r+1.0572252*u))}function fn(n,t,e){return n>0?new on(Math.atan2(e,t)*Cu,Math.sqrt(t*t+e*e),n):new on(NaN,NaN,n)}function sn(n){return n>.206893034?n*n*n:(n-4/29)/7.787037}function hn(n){return n>.008856?Math.pow(n,1/3):7.787037*n+4/29}function pn(n){return Math.round(255*(.00304>=n?12.92*n:1.055*Math.pow(n,1/2.4)-.055))}function gn(n,t,e){return this instanceof gn?(this.r=~~n,this.g=~~t,void(this.b=~~e)):arguments.length<2?n instanceof gn?new gn(n.r,n.g,n.b):mn(""+n,gn,un):new gn(n,t,e)}function vn(n){return new gn(n>>16,n>>8&255,255&n)}function dn(n){return vn(n)+""}function yn(n){return 16>n?"0"+Math.max(0,n).toString(16):Math.min(255,n).toString(16)}function mn(n,t,e){var r,i,u,o=0,a=0,c=0;if(r=/([a-z]+)\((.*)\)/.exec(n=n.toLowerCase()))switch(i=r[2].split(","),r[1]){case"hsl":return e(parseFloat(i[0]),parseFloat(i[1])/100,parseFloat(i[2])/100);case"rgb":return t(_n(i[0]),_n(i[1]),_n(i[2]))}return(u=Yu.get(n))?t(u.r,u.g,u.b):(null==n||"#"!==n.charAt(0)||isNaN(u=parseInt(n.slice(1),16))||(4===n.length?(o=(3840&u)>>4,o|=o>>4,a=240&u,a|=a>>4,c=15&u,c|=c<<4):7===n.length&&(o=(16711680&u)>>16,a=(65280&u)>>8,c=255&u)),t(o,a,c))}function Mn(n,t,e){var r,i,u=Math.min(n/=255,t/=255,e/=255),o=Math.max(n,t,e),a=o-u,c=(o+u)/2;return a?(i=.5>c?a/(o+u):a/(2-o-u),r=n==o?(t-e)/a+(e>t?6:0):t==o?(e-n)/a+2:(n-t)/a+4,r*=60):(r=NaN,i=c>0&&1>c?0:r),new rn(r,i,c)}function xn(n,t,e){var r=hn((.4124564*(n=bn(n))+.3575761*(t=bn(t))+.1804375*(e=bn(e)))/ju),i=hn((.2126729*n+.7151522*t+.072175*e)/Fu);return cn(116*i-16,500*(r-i),200*(i-hn((.0193339*n+.119192*t+.9503041*e)/Hu)))}function bn(n){return(n/=255)<=.04045?n/12.92:Math.pow((n+.055)/1.055,2.4)}function _n(n){var t=parseFloat(n);return"%"===n.charAt(n.length-1)?Math.round(2.55*t):t}function wn(n){return"function"==typeof n?n:function(){return n}}function Sn(n){return function(t,e,r){return 2===arguments.length&&"function"==typeof e&&(r=e,e=null),kn(t,e,n,r)}}function kn(n,t,e,r){function i(){var n,t=c.status;if(!t&&function(n){var t=n.responseType;return t&&"text"!==t?n.response:n.responseText}(c)||t>=200&&300>t||304===t){try{n=e.call(u,c)}catch(n){return void o.error.call(u,n)}o.load.call(u,n)}else o.error.call(u,c)}var u={},o=Ji.dispatch("beforesend","progress","load","error"),a={},c=new XMLHttpRequest,l=null;return!this.XDomainRequest||"withCredentials"in c||!/^(http(s)?:)?\/\//.test(n)||(c=new XDomainRequest),"onload"in c?c.onload=c.onerror=i:c.onreadystatechange=function(){c.readyState>3&&i()},c.onprogress=function(n){var t=Ji.event;Ji.event=n;try{o.progress.call(u,c)}finally{Ji.event=t}},u.header=function(n,t){return n=(n+"").toLowerCase(),arguments.length<2?a[n]:(null==t?delete a[n]:a[n]=t+"",u)},u.mimeType=function(n){return arguments.length?(t=null==n?null:n+"",u):t},u.responseType=function(n){return arguments.length?(l=n,u):l},u.response=function(n){return e=n,u},["get","post"].forEach(function(n){u[n]=function(){return u.send.apply(u,[n].concat(Ki(arguments)))}}),u.send=function(e,r,i){if(2===arguments.length&&"function"==typeof r&&(i=r,r=null),c.open(e,n,!0),null==t||"accept"in a||(a.accept=t+",*/*"),c.setRequestHeader)for(var f in a)c.setRequestHeader(f,a[f]);return null!=t&&c.overrideMimeType&&c.overrideMimeType(t),null!=l&&(c.responseType=l),null!=i&&u.on("error",i).on("load",function(n){i(null,n)}),o.beforesend.call(u,c),c.send(null==r?null:r),u},u.abort=function(){return c.abort(),u},Ji.rebind(u,o,"on"),null==r?u:u.get(function(n){return 1===n.length?function(t,e){n(null==t?e:null)}:n}(r))}function Nn(){var n=En(),t=An()-n;t>24?(isFinite(t)&&(clearTimeout($u),$u=setTimeout(Nn,t)),Xu=0):(Xu=1,Wu(Nn))}function En(){var n=Date.now();for(Bu=Zu;Bu;)n>=Bu.t&&(Bu.f=Bu.c(n-Bu.t)),Bu=Bu.n;return n}function An(){for(var n,t=Zu,e=1/0;t;)t.f?t=n?n.n=t.n:Zu=t.n:(t.t<e&&(e=t.t),t=(n=t).n);return Vu=n,e}function Cn(n,t){return t-(n?Math.ceil(Math.log(n)/Math.LN10):1)}function zn(n){var t=n.decimal,e=n.thousands,r=n.grouping,i=n.currency,u=r&&e?function(n,t){for(var i=n.length,u=[],o=0,a=r[0],c=0;i>0&&a>0&&(c+a+1>t&&(a=Math.max(1,t-c)),u.push(n.substring(i-=a,i+a)),!((c+=a+1)>t));)a=r[o=(o+1)%r.length];return u.reverse().join(e)}:y;return function(n){var e=Gu.exec(n),r=e[1]||" ",o=e[2]||">",a=e[3]||"-",c=e[4]||"",l=e[5],f=+e[6],s=e[7],h=e[8],p=e[9],g=1,v="",d="",y=!1,m=!0;switch(h&&(h=+h.substring(1)),(l||"0"===r&&"="===o)&&(l=r="0",o="="),p){case"n":s=!0,p="g";break;case"%":g=100,d="%",p="f";break;case"p":g=100,d="%",p="r";break;case"b":case"o":case"x":case"X":"#"===c&&(v="0"+p.toLowerCase());case"c":m=!1;case"d":y=!0,h=0;break;case"s":g=-1,p="r"}"$"===c&&(v=i[0],d=i[1]),"r"!=p||h||(p="g"),null!=h&&("g"==p?h=Math.max(1,Math.min(21,h)):("e"==p||"f"==p)&&(h=Math.max(0,Math.min(20,h)))),p=Ku.get(p)||qn;var M=l&&s;return function(n){var e=d;if(y&&n%1)return"";var i=0>n||0===n&&0>1/n?(n=-n,"-"):"-"===a?"":a;if(0>g){var c=Ji.formatPrefix(n,h);n=c.scale(n),e=c.symbol+d}else n*=g;var x,b,_=(n=p(n,h)).lastIndexOf(".");if(0>_){var w=m?n.lastIndexOf("e"):-1;0>w?(x=n,b=""):(x=n.substring(0,w),b=n.substring(w))}else x=n.substring(0,_),b=t+n.substring(_+1);!l&&s&&(x=u(x,1/0));var S=v.length+x.length+b.length+(M?0:i.length),k=f>S?new Array(S=f-S+1).join(r):"";return M&&(x=u(k+x,k.length?f-b.length:1/0)),i+=v,n=x+b,("<"===o?i+n+k:">"===o?k+i+n:"^"===o?k.substring(0,S>>=1)+i+n+k.substring(S):i+(M?n:k+n))+e}}}function qn(n){return n+""}function Ln(){this._=new Date(arguments.length>1?Date.UTC.apply(this,arguments):arguments[0])}function Tn(n,t,e){function r(t){var e=n(t),r=u(e,1);return r-t>t-e?e:r}function i(e){return t(e=n(new no(e-1)),1),e}function u(n,e){return t(n=new no(+n),e),n}function o(n,r,u){var o=i(n),a=[];if(u>1)for(;r>o;)e(o)%u||a.push(new Date(+o)),t(o,1);else for(;r>o;)a.push(new Date(+o)),t(o,1);return a}n.floor=n,n.round=r,n.ceil=i,n.offset=u,n.range=o;var a=n.utc=Rn(n);return a.floor=a,a.round=Rn(r),a.ceil=Rn(i),a.offset=Rn(u),a.range=function(n,t,e){try{no=Ln;var r=new Ln;return r._=n,o(r,t,e)}finally{no=Date}},n}function Rn(n){return function(t,e){try{no=Ln;var r=new Ln;return r._=t,n(r,e)._}finally{no=Date}}}function Dn(n){function t(n){function t(t){for(var e,i,u,o=[],a=-1,c=0;++a<r;)37===n.charCodeAt(a)&&(o.push(n.slice(c,a)),null!=(i=eo[e=n.charAt(++a)])&&(e=n.charAt(++a)),(u=x[e])&&(e=u(t,null==i?"e"===e?" ":"0":i)),o.push(e),c=a+1);return o.push(n.slice(c,a)),o.join("")}var r=n.length;return t.parse=function(t){var r={y:1900,m:0,d:1,H:0,M:0,S:0,L:0,Z:null};if(e(r,n,t,0)!=t.length)return null;"p"in r&&(r.H=r.H%12+12*r.p);var i=null!=r.Z&&no!==Ln,u=new(i?Ln:no);return"j"in r?u.setFullYear(r.y,0,r.j):"w"in r&&("W"in r||"U"in r)?(u.setFullYear(r.y,0,1),u.setFullYear(r.y,0,"W"in r?(r.w+6)%7+7*r.W-(u.getDay()+5)%7:r.w+7*r.U-(u.getDay()+6)%7)):u.setFullYear(r.y,r.m,r.d),u.setHours(r.H+(r.Z/100|0),r.M+r.Z%100,r.S,r.L),i?u._:u},t.toString=function(){return n},t}function e(n,t,e,r){for(var i,u,o,a=0,c=t.length,l=e.length;c>a;){if(r>=l)return-1;if(37===(i=t.charCodeAt(a++))){if(o=t.charAt(a++),!(u=b[o in eo?t.charAt(a++):o])||(r=u(n,e,r))<0)return-1}else if(i!=e.charCodeAt(r++))return-1}return r}var r=n.dateTime,i=n.date,u=n.time,o=n.periods,a=n.days,c=n.shortDays,l=n.months,f=n.shortMonths;t.utc=function(n){function e(n){try{var t=new(no=Ln);return t._=n,r(t)}finally{no=Date}}var r=t(n);return e.parse=function(n){try{no=Ln;var t=r.parse(n);return t&&t._}finally{no=Date}},e.toString=r.toString,e},t.multi=t.utc.multi=nt;var s=Ji.map(),h=Un(a),p=jn(a),g=Un(c),v=jn(c),d=Un(l),y=jn(l),m=Un(f),M=jn(f);o.forEach(function(n,t){s.set(n.toLowerCase(),t)});var x={a:function(n){return c[n.getDay()]},A:function(n){return a[n.getDay()]},b:function(n){return f[n.getMonth()]},B:function(n){return l[n.getMonth()]},c:t(r),d:function(n,t){return Pn(n.getDate(),t,2)},e:function(n,t){return Pn(n.getDate(),t,2)},H:function(n,t){return Pn(n.getHours(),t,2)},I:function(n,t){return Pn(n.getHours()%12||12,t,2)},j:function(n,t){return Pn(1+Qu.dayOfYear(n),t,3)},L:function(n,t){return Pn(n.getMilliseconds(),t,3)},m:function(n,t){return Pn(n.getMonth()+1,t,2)},M:function(n,t){return Pn(n.getMinutes(),t,2)},p:function(n){return o[+(n.getHours()>=12)]},S:function(n,t){return Pn(n.getSeconds(),t,2)},U:function(n,t){return Pn(Qu.sundayOfYear(n),t,2)},w:function(n){return n.getDay()},W:function(n,t){return Pn(Qu.mondayOfYear(n),t,2)},x:t(i),X:t(u),y:function(n,t){return Pn(n.getFullYear()%100,t,2)},Y:function(n,t){return Pn(n.getFullYear()%1e4,t,4)},Z:Kn,"%":function(){return"%"}},b={a:function(n,t,e){g.lastIndex=0;var r=g.exec(t.slice(e));return r?(n.w=v.get(r[0].toLowerCase()),e+r[0].length):-1},A:function(n,t,e){h.lastIndex=0;var r=h.exec(t.slice(e));return r?(n.w=p.get(r[0].toLowerCase()),e+r[0].length):-1},b:function(n,t,e){m.lastIndex=0;var r=m.exec(t.slice(e));return r?(n.m=M.get(r[0].toLowerCase()),e+r[0].length):-1},B:function(n,t,e){d.lastIndex=0;var r=d.exec(t.slice(e));return r?(n.m=y.get(r[0].toLowerCase()),e+r[0].length):-1},c:function(n,t,r){return e(n,x.c.toString(),t,r)},d:Xn,e:Xn,H:Bn,I:Bn,j:$n,L:Gn,m:Vn,M:Wn,p:function(n,t,e){var r=s.get(t.slice(e,e+=2).toLowerCase());return null==r?-1:(n.p=r,e)},S:Jn,U:Hn,w:Fn,W:On,x:function(n,t,r){return e(n,x.x.toString(),t,r)},X:function(n,t,r){return e(n,x.X.toString(),t,r)},y:Yn,Y:In,Z:Zn,"%":Qn};return t}function Pn(n,t,e){var r=0>n?"-":"",i=(r?-n:n)+"",u=i.length;return r+(e>u?new Array(e-u+1).join(t)+i:i)}function Un(n){return new RegExp("^(?:"+n.map(Ji.requote).join("|")+")","i")}function jn(n){for(var t=new c,e=-1,r=n.length;++e<r;)t.set(n[e].toLowerCase(),e);return t}function Fn(n,t,e){ro.lastIndex=0;var r=ro.exec(t.slice(e,e+1));return r?(n.w=+r[0],e+r[0].length):-1}function Hn(n,t,e){ro.lastIndex=0;var r=ro.exec(t.slice(e));return r?(n.U=+r[0],e+r[0].length):-1}function On(n,t,e){ro.lastIndex=0;var r=ro.exec(t.slice(e));return r?(n.W=+r[0],e+r[0].length):-1}function In(n,t,e){ro.lastIndex=0;var r=ro.exec(t.slice(e,e+4));return r?(n.y=+r[0],e+r[0].length):-1}function Yn(n,t,e){ro.lastIndex=0;var r=ro.exec(t.slice(e,e+2));return r?(n.y=function(n){return n+(n>68?1900:2e3)}(+r[0]),e+r[0].length):-1}function Zn(n,t,e){return/^[+-]\d{4}$/.test(t=t.slice(e,e+5))?(n.Z=-t,e+5):-1}function Vn(n,t,e){ro.lastIndex=0;var r=ro.exec(t.slice(e,e+2));return r?(n.m=r[0]-1,e+r[0].length):-1}function Xn(n,t,e){ro.lastIndex=0;var r=ro.exec(t.slice(e,e+2));return r?(n.d=+r[0],e+r[0].length):-1}function $n(n,t,e){ro.lastIndex=0;var r=ro.exec(t.slice(e,e+3));return r?(n.j=+r[0],e+r[0].length):-1}function Bn(n,t,e){ro.lastIndex=0;var r=ro.exec(t.slice(e,e+2));return r?(n.H=+r[0],e+r[0].length):-1}function Wn(n,t,e){ro.lastIndex=0;var r=ro.exec(t.slice(e,e+2));return r?(n.M=+r[0],e+r[0].length):-1}function Jn(n,t,e){ro.lastIndex=0;var r=ro.exec(t.slice(e,e+2));return r?(n.S=+r[0],e+r[0].length):-1}function Gn(n,t,e){ro.lastIndex=0;var r=ro.exec(t.slice(e,e+3));return r?(n.L=+r[0],e+r[0].length):-1}function Kn(n){var t=n.getTimezoneOffset(),e=t>0?"-":"+",r=ou(t)/60|0,i=ou(t)%60;return e+Pn(r,"0",2)+Pn(i,"0",2)}function Qn(n,t,e){io.lastIndex=0;var r=io.exec(t.slice(e,e+1));return r?e+r[0].length:-1}function nt(n){for(var t=n.length,e=-1;++e<t;)n[e][0]=this(n[e][0]);return function(t){for(var e=0,r=n[e];!r[1](t);)r=n[++e];return r[0](t)}}function tt(){}function et(n,t,e){var r=e.s=n+t,i=r-n,u=r-i;e.t=n-u+(t-i)}function rt(n,t){n&&co.hasOwnProperty(n.type)&&co[n.type](n,t)}function it(n,t,e){var r,i=-1,u=n.length-e;for(t.lineStart();++i<u;)r=n[i],t.point(r[0],r[1],r[2]);t.lineEnd()}function ut(n,t){var e=-1,r=n.length;for(t.polygonStart();++e<r;)it(n[e],t,1);t.polygonEnd()}function ot(){function n(n,t){t=t*Au/2+Su/4;var e=(n*=Au)-r,o=e>=0?1:-1,a=o*e,c=Math.cos(t),l=Math.sin(t),f=u*l,s=i*c+f*Math.cos(a),h=f*o*Math.sin(a);fo.add(Math.atan2(h,s)),r=n,i=c,u=l}var t,e,r,i,u;so.point=function(o,a){so.point=n,r=(t=o)*Au,i=Math.cos(a=(e=a)*Au/2+Su/4),u=Math.sin(a)},so.lineEnd=function(){n(t,e)}}function at(n){var t=n[0],e=n[1],r=Math.cos(e);return[r*Math.cos(t),r*Math.sin(t),Math.sin(e)]}function ct(n,t){return n[0]*t[0]+n[1]*t[1]+n[2]*t[2]}function lt(n,t){return[n[1]*t[2]-n[2]*t[1],n[2]*t[0]-n[0]*t[2],n[0]*t[1]-n[1]*t[0]]}function ft(n,t){n[0]+=t[0],n[1]+=t[1],n[2]+=t[2]}function st(n,t){return[n[0]*t,n[1]*t,n[2]*t]}function ht(n){var t=Math.sqrt(n[0]*n[0]+n[1]*n[1]+n[2]*n[2]);n[0]/=t,n[1]/=t,n[2]/=t}function pt(n){return[Math.atan2(n[1],n[0]),Q(n[2])]}function gt(n,t){return ou(n[0]-t[0])<_u&&ou(n[1]-t[1])<_u}function vt(n,t){n*=Au;var e=Math.cos(t*=Au);dt(e*Math.cos(n),e*Math.sin(n),Math.sin(t))}function dt(n,t,e){go+=(n-go)/++ho,vo+=(t-vo)/ho,yo+=(e-yo)/ho}function yt(){function n(n,i){n*=Au;var u=Math.cos(i*=Au),o=u*Math.cos(n),a=u*Math.sin(n),c=Math.sin(i),l=Math.atan2(Math.sqrt((l=e*c-r*a)*l+(l=r*o-t*c)*l+(l=t*a-e*o)*l),t*o+e*a+r*c);po+=l,mo+=l*(t+(t=o)),Mo+=l*(e+(e=a)),xo+=l*(r+(r=c)),dt(t,e,r)}var t,e,r;So.point=function(i,u){i*=Au;var o=Math.cos(u*=Au);t=o*Math.cos(i),e=o*Math.sin(i),r=Math.sin(u),So.point=n,dt(t,e,r)}}function mt(){So.point=vt}function Mt(){function n(n,t){n*=Au;var e=Math.cos(t*=Au),o=e*Math.cos(n),a=e*Math.sin(n),c=Math.sin(t),l=i*c-u*a,f=u*o-r*c,s=r*a-i*o,h=Math.sqrt(l*l+f*f+s*s),p=r*o+i*a+u*c,g=h&&-K(p)/h,v=Math.atan2(h,p);bo+=g*l,_o+=g*f,wo+=g*s,po+=v,mo+=v*(r+(r=o)),Mo+=v*(i+(i=a)),xo+=v*(u+(u=c)),dt(r,i,u)}var t,e,r,i,u;So.point=function(o,a){t=o,e=a,So.point=n,o*=Au;var c=Math.cos(a*=Au);r=c*Math.cos(o),i=c*Math.sin(o),u=Math.sin(a),dt(r,i,u)},So.lineEnd=function(){n(t,e),So.lineEnd=mt,So.point=vt}}function xt(n,t){function e(e,r){return e=n(e,r),t(e[0],e[1])}return n.invert&&t.invert&&(e.invert=function(e,r){return(e=t.invert(e,r))&&n.invert(e[0],e[1])}),e}function bt(){return!0}function _t(n,t,e,r,i){var u=[],o=[];if(n.forEach(function(n){if(!((t=n.length-1)<=0)){var t,e=n[0],r=n[t];if(gt(e,r)){i.lineStart();for(var a=0;t>a;++a)i.point((e=n[a])[0],e[1]);return void i.lineEnd()}var c=new St(e,n,null,!0),l=new St(e,null,c,!1);c.o=l,u.push(c),o.push(l),c=new St(r,n,null,!1),l=new St(r,null,c,!0),c.o=l,u.push(c),o.push(l)}}),o.sort(t),wt(u),wt(o),u.length){for(var a=0,c=e,l=o.length;l>a;++a)o[a].e=c=!c;for(var f,s,h=u[0];;){for(var p=h,g=!0;p.v;)if((p=p.n)===h)return;f=p.z,i.lineStart();do{if(p.v=p.o.v=!0,p.e){if(g)for(a=0,l=f.length;l>a;++a)i.point((s=f[a])[0],s[1]);else r(p.x,p.n.x,1,i);p=p.n}else{if(g)for(a=(f=p.p.z).length-1;a>=0;--a)i.point((s=f[a])[0],s[1]);else r(p.x,p.p.x,-1,i);p=p.p}f=(p=p.o).z,g=!g}while(!p.v);i.lineEnd()}}}function wt(n){if(t=n.length){for(var t,e,r=0,i=n[0];++r<t;)i.n=e=n[r],e.p=i,i=e;i.n=e=n[0],e.p=i}}function St(n,t,e,r){this.x=n,this.z=t,this.o=e,this.e=r,this.v=!1,this.n=this.p=null}function kt(n,t,e,r){return function(i,u){function o(t,e){var r=i(t,e);n(t=r[0],e=r[1])&&u.point(t,e)}function a(n,t){var e=i(n,t);d.point(e[0],e[1])}function c(){m.point=a,d.lineStart()}function l(){m.point=o,d.lineEnd()}function f(n,t){v.push([n,t]);var e=i(n,t);x.point(e[0],e[1])}function s(){x.lineStart(),v=[]}function h(){f(v[0][0],v[0][1]),x.lineEnd();var n,t=x.clean(),e=M.buffer(),r=e.length;if(v.pop(),g.push(v),v=null,r)if(1&t){var i,o=-1;if((r=(n=e[0]).length-1)>0){for(b||(u.polygonStart(),b=!0),u.lineStart();++o<r;)u.point((i=n[o])[0],i[1]);u.lineEnd()}}else r>1&&2&t&&e.push(e.pop().concat(e.shift())),p.push(e.filter(Nt))}var p,g,v,d=t(u),y=i.invert(r[0],r[1]),m={point:o,lineStart:c,lineEnd:l,polygonStart:function(){m.point=f,m.lineStart=s,m.lineEnd=h,p=[],g=[]},polygonEnd:function(){m.point=o,m.lineStart=c,m.lineEnd=l,p=Ji.merge(p);var n=function(n,t){var e=n[0],r=n[1],i=[Math.sin(e),-Math.cos(e),0],u=0,o=0;fo.reset();for(var a=0,c=t.length;c>a;++a){var l=t[a],f=l.length;if(f)for(var s=l[0],h=s[0],p=s[1]/2+Su/4,g=Math.sin(p),v=Math.cos(p),d=1;;){d===f&&(d=0);var y=(n=l[d])[0],m=n[1]/2+Su/4,M=Math.sin(m),x=Math.cos(m),b=y-h,_=b>=0?1:-1,w=_*b,S=w>Su,k=g*M;if(fo.add(Math.atan2(k*_*Math.sin(w),v*x+k*Math.cos(w))),u+=S?b+_*ku:b,S^h>=e^y>=e){var N=lt(at(s),at(n));ht(N);var E=lt(i,N);ht(E);var A=(S^b>=0?-1:1)*Q(E[2]);(r>A||r===A&&(N[0]||N[1]))&&(o+=S^b>=0?1:-1)}if(!d++)break;h=y,g=M,v=x,s=n}}return(-_u>u||_u>u&&0>fo)^1&o}(y,g);p.length?(b||(u.polygonStart(),b=!0),_t(p,At,n,e,u)):n&&(b||(u.polygonStart(),b=!0),u.lineStart(),e(null,null,1,u),u.lineEnd()),b&&(u.polygonEnd(),b=!1),p=g=null},sphere:function(){u.polygonStart(),u.lineStart(),e(null,null,1,u),u.lineEnd(),u.polygonEnd()}},M=Et(),x=t(M),b=!1;return m}}function Nt(n){return n.length>1}function Et(){var n,t=[];return{lineStart:function(){t.push(n=[])},point:function(t,e){n.push([t,e])},lineEnd:x,buffer:function(){var e=t;return t=[],n=null,e},rejoin:function(){t.length>1&&t.push(t.pop().concat(t.shift()))}}}function At(n,t){return((n=n.x)[0]<0?n[1]-Eu-_u:Eu-n[1])-((t=t.x)[0]<0?t[1]-Eu-_u:Eu-t[1])}function Ct(n,t,e,r){return function(i){var u,o=i.a,a=i.b,c=o.x,l=o.y,f=0,s=1,h=a.x-c,p=a.y-l;if(u=n-c,h||!(u>0)){if(u/=h,0>h){if(f>u)return;s>u&&(s=u)}else if(h>0){if(u>s)return;u>f&&(f=u)}if(u=e-c,h||!(0>u)){if(u/=h,0>h){if(u>s)return;u>f&&(f=u)}else if(h>0){if(f>u)return;s>u&&(s=u)}if(u=t-l,p||!(u>0)){if(u/=p,0>p){if(f>u)return;s>u&&(s=u)}else if(p>0){if(u>s)return;u>f&&(f=u)}if(u=r-l,p||!(0>u)){if(u/=p,0>p){if(u>s)return;u>f&&(f=u)}else if(p>0){if(f>u)return;s>u&&(s=u)}return f>0&&(i.a={x:c+f*h,y:l+f*p}),1>s&&(i.b={x:c+s*h,y:l+s*p}),i}}}}}}function zt(n,t,e,r){function i(r,i){return ou(r[0]-n)<_u?i>0?0:3:ou(r[0]-e)<_u?i>0?2:1:ou(r[1]-t)<_u?i>0?1:0:i>0?3:2}function u(n,t){return o(n.x,t.x)}function o(n,t){var e=i(n,1),r=i(t,1);return e!==r?e-r:0===e?t[1]-n[1]:1===e?n[0]-t[0]:2===e?n[1]-t[1]:t[0]-n[0]}return function(a){function c(u,a,c,l){var f=0,s=0;if(null==u||(f=i(u,c))!==(s=i(a,c))||o(u,a)<0^c>0)do{l.point(0===f||3===f?n:e,f>1?r:t)}while((f=(f+c+4)%4)!==s);else l.point(a[0],a[1])}function l(i,u){return i>=n&&e>=i&&u>=t&&r>=u}function f(n,t){l(n,t)&&a.point(n,t)}function s(n,t){var e=l(n=Math.max(-No,Math.min(No,n)),t=Math.max(-No,Math.min(No,t)));if(p&&g.push([n,t]),b)v=n,d=t,y=e,b=!1,e&&(a.lineStart(),a.point(n,t));else if(e&&x)a.point(n,t);else{var r={a:{x:m,y:M},b:{x:n,y:t}};k(r)?(x||(a.lineStart(),a.point(r.a.x,r.a.y)),a.point(r.b.x,r.b.y),e||a.lineEnd(),_=!1):e&&(a.lineStart(),a.point(n,t),_=!1)}m=n,M=t,x=e}var h,p,g,v,d,y,m,M,x,b,_,w=a,S=Et(),k=Ct(n,t,e,r),N={point:f,lineStart:function(){N.point=s,p&&p.push(g=[]),b=!0,x=!1,m=M=NaN},lineEnd:function(){h&&(s(v,d),y&&x&&S.rejoin(),h.push(S.buffer())),N.point=f,x&&a.lineEnd()},polygonStart:function(){a=S,h=[],p=[],_=!0},polygonEnd:function(){a=w,h=Ji.merge(h);var t=function(n){for(var t=0,e=p.length,r=n[1],i=0;e>i;++i)for(var u,o=1,a=p[i],c=a.length,l=a[0];c>o;++o)u=a[o],l[1]<=r?u[1]>r&&G(l,u,n)>0&&++t:u[1]<=r&&G(l,u,n)<0&&--t,l=u;return 0!==t}([n,r]),e=_&&t,i=h.length;(e||i)&&(a.polygonStart(),e&&(a.lineStart(),c(null,null,1,a),a.lineEnd()),i&&_t(h,u,t,c,a),a.polygonEnd()),h=p=g=null}};return N}}function qt(n){var t=0,e=Su/3,r=Vt(n),i=r(t,e);return i.parallels=function(n){return arguments.length?r(t=n[0]*Su/180,e=n[1]*Su/180):[t/Su*180,e/Su*180]},i}function Lt(n,t){function e(n,t){var e=Math.sqrt(u-2*i*Math.sin(t))/i;return[e*Math.sin(n*=i),o-e*Math.cos(n)]}var r=Math.sin(n),i=(r+Math.sin(t))/2,u=1+r*(2*i-r),o=Math.sqrt(u)/i;return e.invert=function(n,t){var e=o-t;return[Math.atan2(n,e)/i,Q((u-(n*n+e*e)*i*i)/(2*i))]},e}function Tt(){function n(n,t){Ao+=i*n-r*t,r=n,i=t}var t,e,r,i;To.point=function(u,o){To.point=n,t=r=u,e=i=o},To.lineEnd=function(){n(t,e)}}function Rt(){function n(n,t){o.push("M",n,",",t,u)}function t(n,t){o.push("M",n,",",t),a.point=e}function e(n,t){o.push("L",n,",",t)}function r(){a.point=n}function i(){o.push("Z")}var u=Dt(4.5),o=[],a={point:n,lineStart:function(){a.point=t},lineEnd:r,polygonStart:function(){a.lineEnd=i},polygonEnd:function(){a.lineEnd=r,a.point=n},pointRadius:function(n){return u=Dt(n),a},result:function(){if(o.length){var n=o.join("");return o=[],n}}};return a}function Dt(n){return"m0,"+n+"a"+n+","+n+" 0 1,1 0,"+-2*n+"a"+n+","+n+" 0 1,1 0,"+2*n+"z"}function Pt(n,t){go+=n,vo+=t,++yo}function Ut(){function n(n,r){var i=n-t,u=r-e,o=Math.sqrt(i*i+u*u);mo+=o*(t+n)/2,Mo+=o*(e+r)/2,xo+=o,Pt(t=n,e=r)}var t,e;Do.point=function(r,i){Do.point=n,Pt(t=r,e=i)}}function jt(){Do.point=Pt}function Ft(){function n(n,t){var e=n-r,u=t-i,o=Math.sqrt(e*e+u*u);mo+=o*(r+n)/2,Mo+=o*(i+t)/2,xo+=o,bo+=(o=i*n-r*t)*(r+n),_o+=o*(i+t),wo+=3*o,Pt(r=n,i=t)}var t,e,r,i;Do.point=function(u,o){Do.point=n,Pt(t=r=u,e=i=o)},Do.lineEnd=function(){n(t,e)}}function Ht(n){function t(t,e){n.moveTo(t+o,e),n.arc(t,e,o,0,ku)}function e(t,e){n.moveTo(t,e),a.point=r}function r(t,e){n.lineTo(t,e)}function i(){a.point=t}function u(){n.closePath()}var o=4.5,a={point:t,lineStart:function(){a.point=e},lineEnd:i,polygonStart:function(){a.lineEnd=u},polygonEnd:function(){a.lineEnd=i,a.point=t},pointRadius:function(n){return o=n,a},result:x};return a}function Ot(n){function t(n){return(a?r:e)(n)}function e(t){return Yt(t,function(e,r){e=n(e,r),t.point(e[0],e[1])})}function r(t){function e(e,r){e=n(e,r),t.point(e[0],e[1])}function r(){m=NaN,w.point=u,t.lineStart()}function u(e,r){var u=at([e,r]),o=n(e,r);i(m,M,y,x,b,_,m=o[0],M=o[1],y=e,x=u[0],b=u[1],_=u[2],a,t),t.point(m,M)}function o(){w.point=e,t.lineEnd()}function c(){r(),w.point=l,w.lineEnd=f}function l(n,t){u(s=n,t),h=m,p=M,g=x,v=b,d=_,w.point=u}function f(){i(m,M,y,x,b,_,h,p,s,g,v,d,a,t),w.lineEnd=o,o()}var s,h,p,g,v,d,y,m,M,x,b,_,w={point:e,lineStart:r,lineEnd:o,polygonStart:function(){t.polygonStart(),w.lineStart=c},polygonEnd:function(){t.polygonEnd(),w.lineStart=r}};return w}function i(t,e,r,a,c,l,f,s,h,p,g,v,d,y){var m=f-t,M=s-e,x=m*m+M*M;if(x>4*u&&d--){var b=a+p,_=c+g,w=l+v,S=Math.sqrt(b*b+_*_+w*w),k=Math.asin(w/=S),N=ou(ou(w)-1)<_u||ou(r-h)<_u?(r+h)/2:Math.atan2(_,b),E=n(N,k),A=E[0],C=E[1],z=A-t,q=C-e,L=M*z-m*q;(L*L/x>u||ou((m*z+M*q)/x-.5)>.3||o>a*p+c*g+l*v)&&(i(t,e,r,a,c,l,A,C,N,b/=S,_/=S,w,d,y),y.point(A,C),i(A,C,N,b,_,w,f,s,h,p,g,v,d,y))}}var u=.5,o=Math.cos(30*Au),a=16;return t.precision=function(n){return arguments.length?(a=(u=n*n)>0&&16,t):Math.sqrt(u)},t}function It(n){this.stream=n}function Yt(n,t){return{point:t,sphere:function(){n.sphere()},lineStart:function(){n.lineStart()},lineEnd:function(){n.lineEnd()},polygonStart:function(){n.polygonStart()},polygonEnd:function(){n.polygonEnd()}}}function Zt(n){return Vt(function(){return n})()}function Vt(n){function t(n){return[(n=a(n[0]*Au,n[1]*Au))[0]*h+c,l-n[1]*h]}function e(n){return(n=a.invert((n[0]-c)/h,(l-n[1])/h))&&[n[0]*Cu,n[1]*Cu]}function r(){a=xt(o=Wt(m,M,x),u);var n=u(v,d);return c=p-n[0]*h,l=g+n[1]*h,i()}function i(){return f&&(f.valid=!1,f=null),t}var u,o,a,c,l,f,s=Ot(function(n,t){return[(n=u(n,t))[0]*h+c,l-n[1]*h]}),h=150,p=480,g=250,v=0,d=0,m=0,M=0,x=0,b=ko,_=y,w=null,S=null;return t.stream=function(n){return f&&(f.valid=!1),(f=Xt(b(o,s(_(n))))).valid=!0,f},t.clipAngle=function(n){return arguments.length?(b=null==n?(w=n,ko):function(n){function t(n,t){return Math.cos(n)*Math.cos(t)>i}function e(n,t,e){var r=[1,0,0],u=lt(at(n),at(t)),o=ct(u,u),a=u[0],c=o-a*a;if(!c)return!e&&n;var l=i*o/c,f=-i*a/c,s=lt(r,u),h=st(r,l);ft(h,st(u,f));var p=s,g=ct(h,p),v=ct(p,p),d=g*g-v*(ct(h,h)-1);if(!(0>d)){var y=Math.sqrt(d),m=st(p,(-g-y)/v);if(ft(m,h),m=pt(m),!e)return m;var M,x=n[0],b=t[0],_=n[1],w=t[1];x>b&&(M=x,x=b,b=M);var S=b-x,k=ou(S-Su)<_u;if(!k&&_>w&&(M=_,_=w,w=M),k||_u>S?k?_+w>0^m[1]<(ou(m[0]-x)<_u?_:w):_<=m[1]&&m[1]<=w:S>Su^(x<=m[0]&&m[0]<=b)){var N=st(p,(-g+y)/v);return ft(N,h),[m,pt(N)]}}}function r(t,e){var r=u?n:Su-n,i=0;return-r>t?i|=1:t>r&&(i|=2),-r>e?i|=4:e>r&&(i|=8),i}var i=Math.cos(n),u=i>0,o=ou(i)>_u;return kt(t,function(n){var i,a,c,l,f;return{lineStart:function(){l=c=!1,f=1},point:function(s,h){var p,g=[s,h],v=t(s,h),d=u?v?0:r(s,h):v?r(s+(0>s?Su:-Su),h):0;if(!i&&(l=c=v)&&n.lineStart(),v!==c&&(p=e(i,g),(gt(i,p)||gt(g,p))&&(g[0]+=_u,g[1]+=_u,v=t(g[0],g[1]))),v!==c)f=0,v?(n.lineStart(),p=e(g,i),n.point(p[0],p[1])):(p=e(i,g),n.point(p[0],p[1]),n.lineEnd()),i=p;else if(o&&i&&u^v){var y;d&a||!(y=e(g,i,!0))||(f=0,u?(n.lineStart(),n.point(y[0][0],y[0][1]),n.point(y[1][0],y[1][1]),n.lineEnd()):(n.point(y[1][0],y[1][1]),n.lineEnd(),n.lineStart(),n.point(y[0][0],y[0][1])))}!v||i&&gt(i,g)||n.point(g[0],g[1]),i=g,c=v,a=d},lineEnd:function(){c&&n.lineEnd(),i=null},clean:function(){return f|(l&&c)<<1}}},Qt(n,6*Au),u?[0,-n]:[-Su,n-Su])}((w=+n)*Au),i()):w},t.clipExtent=function(n){return arguments.length?(S=n,_=n?zt(n[0][0],n[0][1],n[1][0],n[1][1]):y,i()):S},t.scale=function(n){return arguments.length?(h=+n,r()):h},t.translate=function(n){return arguments.length?(p=+n[0],g=+n[1],r()):[p,g]},t.center=function(n){return arguments.length?(v=n[0]%360*Au,d=n[1]%360*Au,r()):[v*Cu,d*Cu]},t.rotate=function(n){return arguments.length?(m=n[0]%360*Au,M=n[1]%360*Au,x=n.length>2?n[2]%360*Au:0,r()):[m*Cu,M*Cu,x*Cu]},Ji.rebind(t,s,"precision"),function(){return u=n.apply(this,arguments),t.invert=u.invert&&e,r()}}function Xt(n){return Yt(n,function(t,e){n.point(t*Au,e*Au)})}function $t(n,t){return[n,t]}function Bt(n,t){return[n>Su?n-ku:-Su>n?n+ku:n,t]}function Wt(n,t,e){return n?t||e?xt(Gt(n),Kt(t,e)):Gt(n):t||e?Kt(t,e):Bt}function Jt(n){return function(t,e){return[(t+=n)>Su?t-ku:-Su>t?t+ku:t,e]}}function Gt(n){var t=Jt(n);return t.invert=Jt(-n),t}function Kt(n,t){function e(n,t){var e=Math.cos(t),a=Math.cos(n)*e,c=Math.sin(n)*e,l=Math.sin(t),f=l*r+a*i;return[Math.atan2(c*u-f*o,a*r-l*i),Q(f*u+c*o)]}var r=Math.cos(n),i=Math.sin(n),u=Math.cos(t),o=Math.sin(t);return e.invert=function(n,t){var e=Math.cos(t),a=Math.cos(n)*e,c=Math.sin(n)*e,l=Math.sin(t),f=l*u-c*o;return[Math.atan2(c*u+l*o,a*r+f*i),Q(f*r-a*i)]},e}function Qt(n,t){var e=Math.cos(n),r=Math.sin(n);return function(i,u,o,a){var c=o*t;null!=i?(i=ne(e,i),u=ne(e,u),(o>0?u>i:i>u)&&(i+=o*ku)):(i=n+o*ku,u=n-.5*c);for(var l,f=i;o>0?f>u:u>f;f-=c)a.point((l=pt([e,-r*Math.cos(f),-r*Math.sin(f)]))[0],l[1])}}function ne(n,t){var e=at(t);e[0]-=n,ht(e);var r=K(-e[1]);return((-e[2]<0?-r:r)+2*Math.PI-_u)%(2*Math.PI)}function te(n,t,e){var r=Ji.range(n,t-_u,e).concat(t);return function(n){return r.map(function(t){return[n,t]})}}function ee(n,t,e){var r=Ji.range(n,t-_u,e).concat(t);return function(n){return r.map(function(t){return[t,n]})}}function re(n){return n.source}function ie(n){return n.target}function ue(n,t){function e(t,e){var r=Math.cos(t),i=Math.cos(e),u=n(r*i);return[u*i*Math.sin(t),u*Math.sin(e)]}return e.invert=function(n,e){var r=Math.sqrt(n*n+e*e),i=t(r),u=Math.sin(i),o=Math.cos(i);return[Math.atan2(n*u,r*o),Math.asin(r&&e*u/r)]},e}function oe(n,t){function e(n,t){o>0?-Eu+_u>t&&(t=-Eu+_u):t>Eu-_u&&(t=Eu-_u);var e=o/Math.pow(i(t),u);return[e*Math.sin(u*n),o-e*Math.cos(u*n)]}var r=Math.cos(n),i=function(n){return Math.tan(Su/4+n/2)},u=n===t?Math.sin(n):Math.log(r/Math.cos(t))/Math.log(i(t)/i(n)),o=r*Math.pow(i(n),u)/u;return u?(e.invert=function(n,t){var e=o-t,r=J(u)*Math.sqrt(n*n+e*e);return[Math.atan2(n,e)/u,2*Math.atan(Math.pow(o/r,1/u))-Eu]},e):ce}function ae(n,t){function e(n,t){var e=u-t;return[e*Math.sin(i*n),u-e*Math.cos(i*n)]}var r=Math.cos(n),i=n===t?Math.sin(n):(r-Math.cos(t))/(t-n),u=r/i+n;return ou(i)<_u?$t:(e.invert=function(n,t){var e=u-t;return[Math.atan2(n,e)/i,u-J(i)*Math.sqrt(n*n+e*e)]},e)}function ce(n,t){return[n,Math.log(Math.tan(Su/4+t/2))]}function le(n){var t,e=Zt(n),r=e.scale,i=e.translate,u=e.clipExtent;return e.scale=function(){var n=r.apply(e,arguments);return n===e?t?e.clipExtent(null):e:n},e.translate=function(){var n=i.apply(e,arguments);return n===e?t?e.clipExtent(null):e:n},e.clipExtent=function(n){var o=u.apply(e,arguments);if(o===e){if(t=null==n){var a=Su*r(),c=i();u([[c[0]-a,c[1]-a],[c[0]+a,c[1]+a]])}}else t&&(o=null);return o},e.clipExtent(null)}function fe(n,t){return[Math.log(Math.tan(Su/4+t/2)),-n]}function se(n){return n[0]}function he(n){return n[1]}function pe(n){for(var t=n.length,e=[0,1],r=2,i=2;t>i;i++){for(;r>1&&G(n[e[r-2]],n[e[r-1]],n[i])<=0;)--r;e[r++]=i}return e.slice(0,r)}function ge(n,t){return n[0]-t[0]||n[1]-t[1]}function ve(n,t,e){return(e[0]-t[0])*(n[1]-t[1])<(e[1]-t[1])*(n[0]-t[0])}function de(n,t,e,r){var i=n[0],u=e[0],o=t[0]-i,a=r[0]-u,c=n[1],l=e[1],f=t[1]-c,s=r[1]-l,h=(a*(c-l)-s*(i-u))/(s*o-a*f);return[i+h*o,c+h*f]}function ye(n){var t=n[0],e=n[n.length-1];return!(t[0]-e[0]||t[1]-e[1])}function me(){Ue(this),this.edge=this.site=this.circle=null}function Me(n){var t=Wo.pop()||new me;return t.site=n,t}function xe(n){Ce(n),Xo.remove(n),Wo.push(n),Ue(n)}function be(n){var t=n.circle,e=t.x,r=t.cy,i={x:e,y:r},u=n.P,o=n.N,a=[n];xe(n);for(var c=u;c.circle&&ou(e-c.circle.x)<_u&&ou(r-c.circle.cy)<_u;)u=c.P,a.unshift(c),xe(c),c=u;a.unshift(c),Ce(c);for(var l=o;l.circle&&ou(e-l.circle.x)<_u&&ou(r-l.circle.cy)<_u;)o=l.N,a.push(l),xe(l),l=o;a.push(l),Ce(l);var f,s=a.length;for(f=1;s>f;++f)l=a[f],c=a[f-1],Re(l.edge,c.site,l.site,i);c=a[0],(l=a[s-1]).edge=Le(c.site,l.site,null,i),Ae(c),Ae(l)}function _e(n){for(var t,e,r,i,u=n.x,o=n.y,a=Xo._;a;)if((r=we(a,o)-u)>_u)a=a.L;else{if(!((i=u-Se(a,o))>_u)){r>-_u?(t=a.P,e=a):i>-_u?(t=a,e=a.N):t=e=a;break}if(!a.R){t=a;break}a=a.R}var c=Me(n);if(Xo.insert(t,c),t||e){if(t===e)return Ce(t),e=Me(t.site),Xo.insert(c,e),c.edge=e.edge=Le(t.site,c.site),Ae(t),void Ae(e);if(!e)return void(c.edge=Le(t.site,c.site));Ce(t),Ce(e);var l=t.site,f=l.x,s=l.y,h=n.x-f,p=n.y-s,g=e.site,v=g.x-f,d=g.y-s,y=2*(h*d-p*v),m=h*h+p*p,M=v*v+d*d,x={x:(d*m-p*M)/y+f,y:(h*M-v*m)/y+s};Re(e.edge,l,g,x),c.edge=Le(l,n,null,x),e.edge=Le(n,g,null,x),Ae(t),Ae(e)}}function we(n,t){var e=n.site,r=e.x,i=e.y,u=i-t;if(!u)return r;var o=n.P;if(!o)return-1/0;var a=(e=o.site).x,c=e.y,l=c-t;if(!l)return a;var f=a-r,s=1/u-1/l,h=f/l;return s?(-h+Math.sqrt(h*h-2*s*(f*f/(-2*l)-c+l/2+i-u/2)))/s+r:(r+a)/2}function Se(n,t){var e=n.N;if(e)return we(e,t);var r=n.site;return r.y===t?r.x:1/0}function ke(n){this.site=n,this.edges=[]}function Ne(n,t){return t.angle-n.angle}function Ee(){Ue(this),this.x=this.y=this.arc=this.site=this.cy=null}function Ae(n){var t=n.P,e=n.N;if(t&&e){var r=t.site,i=n.site,u=e.site;if(r!==u){var o=i.x,a=i.y,c=r.x-o,l=r.y-a,f=u.x-o,s=2*(c*(d=u.y-a)-l*f);if(!(s>=-wu)){var h=c*c+l*l,p=f*f+d*d,g=(d*h-l*p)/s,v=(c*p-f*h)/s,d=v+a,y=Jo.pop()||new Ee;y.arc=n,y.site=i,y.x=g+o,y.y=d+Math.sqrt(g*g+v*v),y.cy=d,n.circle=y;for(var m=null,M=Bo._;M;)if(y.y<M.y||y.y===M.y&&y.x<=M.x){if(!M.L){m=M.P;break}M=M.L}else{if(!M.R){m=M;break}M=M.R}Bo.insert(m,y),m||($o=y)}}}}function Ce(n){var t=n.circle;t&&(t.P||($o=t.N),Bo.remove(t),Jo.push(t),Ue(t),n.circle=null)}function ze(n,t){var e=n.b;if(e)return!0;var r,i,u=n.a,o=t[0][0],a=t[1][0],c=t[0][1],l=t[1][1],f=n.l,s=n.r,h=f.x,p=f.y,g=s.x,v=s.y,d=(h+g)/2,y=(p+v)/2;if(v===p){if(o>d||d>=a)return;if(h>g){if(u){if(u.y>=l)return}else u={x:d,y:c};e={x:d,y:l}}else{if(u){if(u.y<c)return}else u={x:d,y:l};e={x:d,y:c}}}else if(i=y-(r=(h-g)/(v-p))*d,-1>r||r>1)if(h>g){if(u){if(u.y>=l)return}else u={x:(c-i)/r,y:c};e={x:(l-i)/r,y:l}}else{if(u){if(u.y<c)return}else u={x:(l-i)/r,y:l};e={x:(c-i)/r,y:c}}else if(v>p){if(u){if(u.x>=a)return}else u={x:o,y:r*o+i};e={x:a,y:r*a+i}}else{if(u){if(u.x<o)return}else u={x:a,y:r*a+i};e={x:o,y:r*o+i}}return n.a=u,n.b=e,!0}function qe(n,t){this.l=n,this.r=t,this.a=this.b=null}function Le(n,t,e,r){var i=new qe(n,t);return Zo.push(i),e&&Re(i,n,t,e),r&&Re(i,t,n,r),Vo[n.i].edges.push(new De(i,n,t)),Vo[t.i].edges.push(new De(i,t,n)),i}function Te(n,t,e){var r=new qe(n,null);return r.a=t,r.b=e,Zo.push(r),r}function Re(n,t,e,r){n.a||n.b?n.l===e?n.b=r:n.a=r:(n.a=r,n.l=t,n.r=e)}function De(n,t,e){var r=n.a,i=n.b;this.edge=n,this.site=t,this.angle=e?Math.atan2(e.y-t.y,e.x-t.x):n.l===t?Math.atan2(i.x-r.x,r.y-i.y):Math.atan2(r.x-i.x,i.y-r.y)}function Pe(){this._=null}function Ue(n){n.U=n.C=n.L=n.R=n.P=n.N=null}function je(n,t){var e=t,r=t.R,i=e.U;i?i.L===e?i.L=r:i.R=r:n._=r,r.U=i,e.U=r,e.R=r.L,e.R&&(e.R.U=e),r.L=e}function Fe(n,t){var e=t,r=t.L,i=e.U;i?i.L===e?i.L=r:i.R=r:n._=r,r.U=i,e.U=r,e.L=r.R,e.L&&(e.L.U=e),r.R=e}function He(n){for(;n.L;)n=n.L;return n}function Oe(n,t){var e,r,i,u=n.sort(Ie).pop();for(Zo=[],Vo=new Array(n.length),Xo=new Pe,Bo=new Pe;;)if(i=$o,u&&(!i||u.y<i.y||u.y===i.y&&u.x<i.x))(u.x!==e||u.y!==r)&&(Vo[u.i]=new ke(u),_e(u),e=u.x,r=u.y),u=n.pop();else{if(!i)break;be(i.arc)}t&&(function(n){for(var t,e=Zo,r=Ct(n[0][0],n[0][1],n[1][0],n[1][1]),i=e.length;i--;)(!ze(t=e[i],n)||!r(t)||ou(t.a.x-t.b.x)<_u&&ou(t.a.y-t.b.y)<_u)&&(t.a=t.b=null,e.splice(i,1))}(t),function(n){for(var t,e,r,i,u,o,a,c,l,f,s=n[0][0],h=n[1][0],p=n[0][1],g=n[1][1],v=Vo,d=v.length;d--;)if((u=v[d])&&u.prepare())for(c=(a=u.edges).length,o=0;c>o;)r=(f=a[o].end()).x,i=f.y,t=(l=a[++o%c].start()).x,e=l.y,(ou(r-t)>_u||ou(i-e)>_u)&&(a.splice(o,0,new De(Te(u.site,f,ou(r-s)<_u&&g-i>_u?{x:s,y:ou(t-s)<_u?e:g}:ou(i-g)<_u&&h-r>_u?{x:ou(e-g)<_u?t:h,y:g}:ou(r-h)<_u&&i-p>_u?{x:h,y:ou(t-h)<_u?e:p}:ou(i-p)<_u&&r-s>_u?{x:ou(e-p)<_u?t:s,y:p}:null),u.site,null)),++c)}(t));var o={cells:Vo,edges:Zo};return Xo=Bo=Zo=Vo=null,o}function Ie(n,t){return t.y-n.y||t.x-n.x}function Ye(n,t,e){return(n.x-e.x)*(t.y-n.y)-(n.x-t.x)*(e.y-n.y)}function Ze(n){return n.x}function Ve(n){return n.y}function Xe(n,t){n=Ji.rgb(n),t=Ji.rgb(t);var e=n.r,r=n.g,i=n.b,u=t.r-e,o=t.g-r,a=t.b-i;return function(n){return"#"+yn(Math.round(e+u*n))+yn(Math.round(r+o*n))+yn(Math.round(i+a*n))}}function $e(n,t){var e,r={},i={};for(e in n)e in t?r[e]=Je(n[e],t[e]):i[e]=n[e];for(e in t)e in n||(i[e]=t[e]);return function(n){for(e in r)i[e]=r[e](n);return i}}function Be(n,t){return n=+n,t=+t,function(e){return n*(1-e)+t*e}}function We(n,t){var e,r,i,u=Ko.lastIndex=Qo.lastIndex=0,o=-1,a=[],c=[];for(n+="",t+="";(e=Ko.exec(n))&&(r=Qo.exec(t));)(i=r.index)>u&&(i=t.slice(u,i),a[o]?a[o]+=i:a[++o]=i),(e=e[0])===(r=r[0])?a[o]?a[o]+=r:a[++o]=r:(a[++o]=null,c.push({i:o,x:Be(e,r)})),u=Qo.lastIndex;return u<t.length&&(i=t.slice(u),a[o]?a[o]+=i:a[++o]=i),a.length<2?c[0]?(t=c[0].x,function(n){return t(n)+""}):function(){return t}:(t=c.length,function(n){for(var e,r=0;t>r;++r)a[(e=c[r]).i]=e.x(n);return a.join("")})}function Je(n,t){for(var e,r=Ji.interpolators.length;--r>=0&&!(e=Ji.interpolators[r](n,t)););return e}function Ge(n,t){var e,r=[],i=[],u=n.length,o=t.length,a=Math.min(n.length,t.length);for(e=0;a>e;++e)r.push(Je(n[e],t[e]));for(;u>e;++e)i[e]=n[e];for(;o>e;++e)i[e]=t[e];return function(n){for(e=0;a>e;++e)i[e]=r[e](n);return i}}function Ke(n){return function(t){return 1-n(1-t)}}function Qe(n){return function(t){return.5*(.5>t?n(2*t):2-n(2-2*t))}}function nr(n){return n*n}function tr(n){return n*n*n}function er(n){if(0>=n)return 0;if(n>=1)return 1;var t=n*n,e=t*n;return 4*(.5>n?e:3*(n-t)+e-.75)}function rr(n){return 1-Math.cos(n*Eu)}function ir(n){return Math.pow(2,10*(n-1))}function ur(n){return 1-Math.sqrt(1-n*n)}function or(n){return 1/2.75>n?7.5625*n*n:2/2.75>n?7.5625*(n-=1.5/2.75)*n+.75:2.5/2.75>n?7.5625*(n-=2.25/2.75)*n+.9375:7.5625*(n-=2.625/2.75)*n+.984375}function ar(n,t){return t-=n,function(e){return Math.round(n+t*e)}}function cr(n){var t=[n.a,n.b],e=[n.c,n.d],r=fr(t),i=lr(t,e),u=fr(function(n,t,e){return n[0]+=e*t[0],n[1]+=e*t[1],n}(e,t,-i))||0;t[0]*e[1]<e[0]*t[1]&&(t[0]*=-1,t[1]*=-1,r*=-1,i*=-1),this.rotate=(r?Math.atan2(t[1],t[0]):Math.atan2(-e[0],e[1]))*Cu,this.translate=[n.e,n.f],this.scale=[r,u],this.skew=u?Math.atan2(i,u)*Cu:0}function lr(n,t){return n[0]*t[0]+n[1]*t[1]}function fr(n){var t=Math.sqrt(lr(n,n));return t&&(n[0]/=t,n[1]/=t),t}function sr(n,t){var e,r=[],i=[],u=Ji.transform(n),o=Ji.transform(t),a=u.translate,c=o.translate,l=u.rotate,f=o.rotate,s=u.skew,h=o.skew,p=u.scale,g=o.scale;return a[0]!=c[0]||a[1]!=c[1]?(r.push("translate(",null,",",null,")"),i.push({i:1,x:Be(a[0],c[0])},{i:3,x:Be(a[1],c[1])})):r.push(c[0]||c[1]?"translate("+c+")":""),l!=f?(l-f>180?f+=360:f-l>180&&(l+=360),i.push({i:r.push(r.pop()+"rotate(",null,")")-2,x:Be(l,f)})):f&&r.push(r.pop()+"rotate("+f+")"),s!=h?i.push({i:r.push(r.pop()+"skewX(",null,")")-2,x:Be(s,h)}):h&&r.push(r.pop()+"skewX("+h+")"),p[0]!=g[0]||p[1]!=g[1]?(e=r.push(r.pop()+"scale(",null,",",null,")"),i.push({i:e-4,x:Be(p[0],g[0])},{i:e-2,x:Be(p[1],g[1])})):(1!=g[0]||1!=g[1])&&r.push(r.pop()+"scale("+g+")"),e=i.length,function(n){for(var t,u=-1;++u<e;)r[(t=i[u]).i]=t.x(n);return r.join("")}}function hr(n,t){return t=(t-=n=+n)||1/t,function(e){return(e-n)/t}}function pr(n,t){return t=(t-=n=+n)||1/t,function(e){return Math.max(0,Math.min(1,(e-n)/t))}}function gr(n){for(var t=n.source,e=n.target,r=function(n,t){if(n===t)return n;for(var e=vr(n),r=vr(t),i=e.pop(),u=r.pop(),o=null;i===u;)o=i,i=e.pop(),u=r.pop();return o}(t,e),i=[t];t!==r;)t=t.parent,i.push(t);for(var u=i.length;e!==r;)i.splice(u,0,e),e=e.parent;return i}function vr(n){for(var t=[],e=n.parent;null!=e;)t.push(n),n=e,e=e.parent;return t.push(n),t}function dr(n){n.fixed|=2}function yr(n){n.fixed&=-7}function mr(n){n.fixed|=4,n.px=n.x,n.py=n.y}function Mr(n){n.fixed&=-5}function xr(n,t){return Ji.rebind(n,t,"sort","children","value"),n.nodes=n,n.links=Nr,n}function br(n,t){for(var e=[n];null!=(n=e.pop());)if(t(n),(i=n.children)&&(r=i.length))for(var r,i;--r>=0;)e.push(i[r])}function _r(n,t){for(var e=[n],r=[];null!=(n=e.pop());)if(r.push(n),(u=n.children)&&(i=u.length))for(var i,u,o=-1;++o<i;)e.push(u[o]);for(;null!=(n=r.pop());)t(n)}function wr(n){return n.children}function Sr(n){return n.value}function kr(n,t){return t.value-n.value}function Nr(n){return Ji.merge(n.map(function(n){return(n.children||[]).map(function(t){return{source:n,target:t}})}))}function Er(n){return n.x}function Ar(n){return n.y}function Cr(n,t,e){n.y0=t,n.y=e}function zr(n){return Ji.range(n.length)}function qr(n){for(var t=-1,e=n[0].length,r=[];++t<e;)r[t]=0;return r}function Lr(n){for(var t,e=1,r=0,i=n[0][1],u=n.length;u>e;++e)(t=n[e][1])>i&&(r=e,i=t);return r}function Tr(n){return n.reduce(Rr,0)}function Rr(n,t){return n+t[1]}function Dr(n,t){return Pr(n,Math.ceil(Math.log(t.length)/Math.LN2+1))}function Pr(n,t){for(var e=-1,r=+n[0],i=(n[1]-r)/t,u=[];++e<=t;)u[e]=i*e+r;return u}function Ur(n){return[Ji.min(n),Ji.max(n)]}function jr(n,t){return n.value-t.value}function Fr(n,t){var e=n._pack_next;n._pack_next=t,t._pack_prev=n,t._pack_next=e,e._pack_prev=t}function Hr(n,t){n._pack_next=t,t._pack_prev=n}function Or(n,t){var e=t.x-n.x,r=t.y-n.y,i=n.r+t.r;return.999*i*i>e*e+r*r}function Ir(n){function t(n){f=Math.min(n.x-n.r,f),s=Math.max(n.x+n.r,s),h=Math.min(n.y-n.r,h),p=Math.max(n.y+n.r,p)}if((e=n.children)&&(l=e.length)){var e,r,i,u,o,a,c,l,f=1/0,s=-1/0,h=1/0,p=-1/0;if(e.forEach(Yr),(r=e[0]).x=-r.r,r.y=0,t(r),l>1&&((i=e[1]).x=i.r,i.y=0,t(i),l>2))for(Vr(r,i,u=e[2]),t(u),Fr(r,u),r._pack_prev=u,Fr(u,i),i=r._pack_next,o=3;l>o;o++){Vr(r,i,u=e[o]);var g=0,v=1,d=1;for(a=i._pack_next;a!==i;a=a._pack_next,v++)if(Or(a,u)){g=1;break}if(1==g)for(c=r._pack_prev;c!==a._pack_prev&&!Or(c,u);c=c._pack_prev,d++);g?(d>v||v==d&&i.r<r.r?Hr(r,i=a):Hr(r=c,i),o--):(Fr(r,u),i=u,t(u))}var y=(f+s)/2,m=(h+p)/2,M=0;for(o=0;l>o;o++)(u=e[o]).x-=y,u.y-=m,M=Math.max(M,u.r+Math.sqrt(u.x*u.x+u.y*u.y));n.r=M,e.forEach(Zr)}}function Yr(n){n._pack_next=n._pack_prev=n}function Zr(n){delete n._pack_next,delete n._pack_prev}function Vr(n,t,e){var r=n.r+e.r,i=t.x-n.x,u=t.y-n.y;if(r&&(i||u)){var o=t.r+e.r,a=i*i+u*u,c=.5+((r*=r)-(o*=o))/(2*a),l=Math.sqrt(Math.max(0,2*o*(r+a)-(r-=a)*r-o*o))/(2*a);e.x=n.x+c*i+l*u,e.y=n.y+c*u-l*i}else e.x=n.x+r,e.y=n.y}function Xr(n,t){return n.parent==t.parent?1:2}function $r(n){var t=n.children;return t.length?t[0]:n.t}function Br(n){var t,e=n.children;return(t=e.length)?e[t-1]:n.t}function Wr(n,t,e){var r=e/(t.i-n.i);t.c-=r,t.s+=e,n.c+=r,t.z+=e,t.m+=e}function Jr(n,t,e){return n.a.parent===t.parent?n.a:e}function Gr(n){return{x:n.x,y:n.y,dx:n.dx,dy:n.dy}}function Kr(n,t){var e=n.x+t[3],r=n.y+t[0],i=n.dx-t[1]-t[3],u=n.dy-t[0]-t[2];return 0>i&&(e+=i/2,i=0),0>u&&(r+=u/2,u=0),{x:e,y:r,dx:i,dy:u}}function Qr(n){var t=n[0],e=n[n.length-1];return e>t?[t,e]:[e,t]}function ni(n){return n.rangeExtent?n.rangeExtent():Qr(n.range())}function ti(n,t,e,r){var i=e(n[0],n[1]),u=r(t[0],t[1]);return function(n){return u(i(n))}}function ei(n,t){var e,r=0,i=n.length-1,u=n[r],o=n[i];return u>o&&(e=r,r=i,i=e,e=u,u=o,o=e),n[r]=t.floor(u),n[i]=t.ceil(o),n}function ri(n,t,e,r){var i=[],u=[],o=0,a=Math.min(n.length,t.length)-1;for(n[a]<n[0]&&(n=n.slice().reverse(),t=t.slice().reverse());++o<=a;)i.push(e(n[o-1],n[o])),u.push(r(t[o-1],t[o]));return function(t){var e=Ji.bisect(n,t,1,a)-1;return u[e](i[e](t))}}function ii(n,t){return Ji.rebind(n,t,"range","rangeRound","interpolate","clamp")}function ui(n,t){return ei(n,function(n){return n?{floor:function(t){return Math.floor(t/n)*n},ceil:function(t){return Math.ceil(t/n)*n}}:fa}(oi(n,t)[2]))}function oi(n,t){null==t&&(t=10);var e=Qr(n),r=e[1]-e[0],i=Math.pow(10,Math.floor(Math.log(r/t)/Math.LN10)),u=t/r*i;return.15>=u?i*=10:.35>=u?i*=5:.75>=u&&(i*=2),e[0]=Math.ceil(e[0]/i)*i,e[1]=Math.floor(e[1]/i)*i+.5*i,e[2]=i,e}function ai(n,t){return Ji.range.apply(Ji,oi(n,t))}function ci(n,t,e){var r=oi(n,t);if(e){var i=Gu.exec(e);if(i.shift(),"s"===i[8]){var u=Ji.formatPrefix(Math.max(ou(r[0]),ou(r[1])));return i[7]||(i[7]="."+li(u.scale(r[2]))),i[8]="f",e=Ji.format(i.join("")),function(n){return e(u.scale(n))+u.symbol}}i[7]||(i[7]="."+function(n,t){var e=li(t[2]);return n in sa?Math.abs(e-li(Math.max(ou(t[0]),ou(t[1]))))+ +("e"!==n):e-2*("%"===n)}(i[8],r)),e=i.join("")}else e=",."+li(r[2])+"f";return Ji.format(e)}function li(n){return-Math.floor(Math.log(n)/Math.LN10+.01)}function fi(n){return function(t){return 0>t?-Math.pow(-t,n):Math.pow(t,n)}}function si(){return 0}function hi(n){return n.innerRadius}function pi(n){return n.outerRadius}function gi(n){return n.startAngle}function vi(n){return n.endAngle}function di(n){return n&&n.padAngle}function yi(n,t,e,r){return(n-e)*t-(t-r)*n>0?0:1}function mi(n,t,e,r,i){var u=n[0]-t[0],o=n[1]-t[1],a=(i?r:-r)/Math.sqrt(u*u+o*o),c=a*o,l=-a*u,f=n[0]+c,s=n[1]+l,h=t[0]+c,p=t[1]+l,g=(f+h)/2,v=(s+p)/2,d=h-f,y=p-s,m=d*d+y*y,M=e-r,x=f*p-h*s,b=(0>y?-1:1)*Math.sqrt(M*M*m-x*x),_=(x*y-d*b)/m,w=(-x*d-y*b)/m,S=(x*y+d*b)/m,k=(-x*d+y*b)/m,N=_-g,E=w-v,A=S-g,C=k-v;return N*N+E*E>A*A+C*C&&(_=S,w=k),[[_-c,w-l],[_*e/M,w*e/M]]}function Mi(n){function t(t){function o(){l.push("M",u(n(f),a))}for(var c,l=[],f=[],s=-1,h=t.length,p=wn(e),g=wn(r);++s<h;)i.call(this,c=t[s],s)?f.push([+p.call(this,c,s),+g.call(this,c,s)]):f.length&&(o(),f=[]);return f.length&&o(),l.length?l.join(""):null}var e=se,r=he,i=bt,u=xi,o=u.key,a=.7;return t.x=function(n){return arguments.length?(e=n,t):e},t.y=function(n){return arguments.length?(r=n,t):r},t.defined=function(n){return arguments.length?(i=n,t):i},t.interpolate=function(n){return arguments.length?(o="function"==typeof n?u=n:(u=Ma.get(n)||xi).key,t):o},t.tension=function(n){return arguments.length?(a=n,t):a},t}function xi(n){return n.join("L")}function bi(n){for(var t=0,e=n.length,r=n[0],i=[r[0],",",r[1]];++t<e;)i.push("V",(r=n[t])[1],"H",r[0]);return i.join("")}function _i(n){for(var t=0,e=n.length,r=n[0],i=[r[0],",",r[1]];++t<e;)i.push("H",(r=n[t])[0],"V",r[1]);return i.join("")}function wi(n,t){if(t.length<1||n.length!=t.length&&n.length!=t.length+2)return xi(n);var e=n.length!=t.length,r="",i=n[0],u=n[1],o=t[0],a=o,c=1;if(e&&(r+="Q"+(u[0]-2*o[0]/3)+","+(u[1]-2*o[1]/3)+","+u[0]+","+u[1],i=n[1],c=2),t.length>1){a=t[1],u=n[c],c++,r+="C"+(i[0]+o[0])+","+(i[1]+o[1])+","+(u[0]-a[0])+","+(u[1]-a[1])+","+u[0]+","+u[1];for(var l=2;l<t.length;l++,c++)u=n[c],a=t[l],r+="S"+(u[0]-a[0])+","+(u[1]-a[1])+","+u[0]+","+u[1]}if(e){var f=n[c];r+="Q"+(u[0]+2*a[0]/3)+","+(u[1]+2*a[1]/3)+","+f[0]+","+f[1]}return r}function Si(n,t){for(var e,r=[],i=(1-t)/2,u=n[0],o=n[1],a=1,c=n.length;++a<c;)e=u,u=o,o=n[a],r.push([i*(o[0]-e[0]),i*(o[1]-e[1])]);return r}function ki(n){if(n.length<3)return xi(n);var t=1,e=n.length,r=n[0],i=r[0],u=r[1],o=[i,i,i,(r=n[1])[0]],a=[u,u,u,r[1]],c=[i,",",u,"L",Ni(_a,o),",",Ni(_a,a)];for(n.push(n[e-1]);++t<=e;)r=n[t],o.shift(),o.push(r[0]),a.shift(),a.push(r[1]),Ei(c,o,a);return n.pop(),c.push("L",r),c.join("")}function Ni(n,t){return n[0]*t[0]+n[1]*t[1]+n[2]*t[2]+n[3]*t[3]}function Ei(n,t,e){n.push("C",Ni(xa,t),",",Ni(xa,e),",",Ni(ba,t),",",Ni(ba,e),",",Ni(_a,t),",",Ni(_a,e))}function Ai(n,t){return(t[1]-n[1])/(t[0]-n[0])}function Ci(n){for(var t,e,r,i,u=[],o=function(n){for(var t=0,e=n.length-1,r=[],i=n[0],u=n[1],o=r[0]=Ai(i,u);++t<e;)r[t]=(o+(o=Ai(i=u,u=n[t+1])))/2;return r[t]=o,r}(n),a=-1,c=n.length-1;++a<c;)t=Ai(n[a],n[a+1]),ou(t)<_u?o[a]=o[a+1]=0:(i=(e=o[a]/t)*e+(r=o[a+1]/t)*r)>9&&(i=3*t/Math.sqrt(i),o[a]=i*e,o[a+1]=i*r);for(a=-1;++a<=c;)i=(n[Math.min(c,a+1)][0]-n[Math.max(0,a-1)][0])/(6*(1+o[a]*o[a])),u.push([i||0,o[a]*i||0]);return u}function zi(n){for(var t,e,r,i=-1,u=n.length;++i<u;)e=(t=n[i])[0],r=t[1]-Eu,t[0]=e*Math.cos(r),t[1]=e*Math.sin(r);return n}function qi(n){function t(t){function c(){v.push("M",a(n(y),s),f,l(n(d.reverse()),s),"Z")}for(var h,p,g,v=[],d=[],y=[],m=-1,M=t.length,x=wn(e),b=wn(i),_=e===r?function(){return p}:wn(r),w=i===u?function(){return g}:wn(u);++m<M;)o.call(this,h=t[m],m)?(d.push([p=+x.call(this,h,m),g=+b.call(this,h,m)]),y.push([+_.call(this,h,m),+w.call(this,h,m)])):d.length&&(c(),d=[],y=[]);return d.length&&c(),v.length?v.join(""):null}var e=se,r=se,i=0,u=he,o=bt,a=xi,c=a.key,l=a,f="L",s=.7;return t.x=function(n){return arguments.length?(e=r=n,t):r},t.x0=function(n){return arguments.length?(e=n,t):e},t.x1=function(n){return arguments.length?(r=n,t):r},t.y=function(n){return arguments.length?(i=u=n,t):u},t.y0=function(n){return arguments.length?(i=n,t):i},t.y1=function(n){return arguments.length?(u=n,t):u},t.defined=function(n){return arguments.length?(o=n,t):o},t.interpolate=function(n){return arguments.length?(c="function"==typeof n?a=n:(a=Ma.get(n)||xi).key,l=a.reverse||a,f=a.closed?"M":"L",t):c},t.tension=function(n){return arguments.length?(s=n,t):s},t}function Li(n){return n.radius}function Ti(n){return[n.x,n.y]}function Ri(){return 64}function Di(){return"circle"}function Pi(n){var t=Math.sqrt(n/Su);return"M0,"+t+"A"+t+","+t+" 0 1,1 0,"+-t+"A"+t+","+t+" 0 1,1 0,"+t+"Z"}function Ui(n){return function(){var t,e;(t=this[n])&&(e=t[t.active])&&(--t.count?delete t[t.active]:delete this[n],t.active+=.5,e.event&&e.event.interrupt.call(this,this.__data__,e.index))}}function ji(n,t,e){return su(n,Ca),n.namespace=t,n.id=e,n}function Fi(n,t,e,r){var i=n.id,u=n.namespace;return I(n,"function"==typeof e?function(n,o,a){n[u][i].tween.set(t,r(e.call(n,n.__data__,o,a)))}:(e=r(e),function(n){n[u][i].tween.set(t,e)}))}function Hi(n){return null==n&&(n=""),function(){this.textContent=n}}function Oi(n){return null==n?"__transition__":"__transition_"+n+"__"}function Ii(n,t,e,r,i){var u=n[e]||(n[e]={active:0,count:0}),o=u[r];if(!o){var a=i.time;o=u[r]={tween:new c,time:a,delay:i.delay,duration:i.duration,ease:i.ease,index:t},i=null,++u.count,Ji.timer(function(i){function c(e){if(u.active>r)return f();var i=u[u.active];i&&(--u.count,delete u[u.active],i.event&&i.event.interrupt.call(n,n.__data__,i.index)),u.active=r,o.event&&o.event.start.call(n,n.__data__,t),o.tween.forEach(function(e,r){(r=r.call(n,n.__data__,t))&&v.push(r)}),h=o.ease,s=o.duration,Ji.timer(function(){return g.c=l(e||1)?bt:l,1},0,a)}function l(e){if(u.active!==r)return 1;for(var i=e/s,a=h(i),c=v.length;c>0;)v[--c].call(n,a);return i>=1?(o.event&&o.event.end.call(n,n.__data__,t),f()):void 0}function f(){return--u.count?delete u[r]:delete n[e],1}var s,h,p=o.delay,g=Bu,v=[];return g.t=p+a,i>=p?c(i-p):void(g.c=c)},0,a)}}function Yi(n,t,e){n.attr("transform",function(n){var r=t(n);return"translate("+(isFinite(r)?r:e(n))+",0)"})}function Zi(n,t,e){n.attr("transform",function(n){var r=t(n);return"translate(0,"+(isFinite(r)?r:e(n))+")"})}function Vi(n){return n.toISOString()}function Xi(n,t,e){function r(t){return n(t)}function i(n,e){var r=(n[1]-n[0])/e,i=Ji.bisect(ja,r);return i==ja.length?[t.year,oi(n.map(function(n){return n/31536e6}),e)[2]]:i?t[r/ja[i-1]<ja[i]/r?i-1:i]:[Oa,oi(n,e)[2]]}return r.invert=function(t){return $i(n.invert(t))},r.domain=function(t){return arguments.length?(n.domain(t),r):n.domain().map($i)},r.nice=function(n,t){function e(e){return!isNaN(e)&&!n.range(e,$i(+e+1),t).length}var u=r.domain(),o=Qr(u),a=null==n?i(o,10):"number"==typeof n&&i(o,n);return a&&(n=a[0],t=a[1]),r.domain(ei(u,t>1?{floor:function(t){for(;e(t=n.floor(t));)t=$i(t-1);return t},ceil:function(t){for(;e(t=n.ceil(t));)t=$i(+t+1);return t}}:n))},r.ticks=function(n,t){var e=Qr(r.domain()),u=null==n?i(e,10):"number"==typeof n?i(e,n):!n.range&&[{range:n},t];return u&&(n=u[0],t=u[1]),n.range(e[0],$i(+e[1]+1),1>t?1:t)},r.tickFormat=function(){return e},r.copy=function(){return Xi(n.copy(),t,e)},ii(r,n)}function $i(n){return new Date(n)}function Bi(n){return JSON.parse(n.responseText)}function Wi(n){var t=Qi.createRange();return t.selectNode(Qi.body),t.createContextualFragment(n.responseText)}var Ji={version:"3.5.6"},Gi=[].slice,Ki=function(n){return Gi.call(n)},Qi=this.document;if(Qi)try{Ki(Qi.documentElement.childNodes)[0].nodeType}catch(n){Ki=function(n){for(var t=n.length,e=new Array(t);t--;)e[t]=n[t];return e}}if(Date.now||(Date.now=function(){return+new Date}),Qi)try{Qi.createElement("DIV").style.setProperty("opacity",0,"")}catch(n){var nu=this.Element.prototype,tu=nu.setAttribute,eu=nu.setAttributeNS,ru=this.CSSStyleDeclaration.prototype,iu=ru.setProperty;nu.setAttribute=function(n,t){tu.call(this,n,t+"")},nu.setAttributeNS=function(n,t,e){eu.call(this,n,t,e+"")},ru.setProperty=function(n,t,e){iu.call(this,n,t+"",e)}}Ji.ascending=e,Ji.descending=function(n,t){return n>t?-1:t>n?1:t>=n?0:NaN},Ji.min=function(n,t){var e,r,i=-1,u=n.length;if(1===arguments.length){for(;++i<u;)if(null!=(r=n[i])&&r>=r){e=r;break}for(;++i<u;)null!=(r=n[i])&&e>r&&(e=r)}else{for(;++i<u;)if(null!=(r=t.call(n,n[i],i))&&r>=r){e=r;break}for(;++i<u;)null!=(r=t.call(n,n[i],i))&&e>r&&(e=r)}return e},Ji.max=function(n,t){var e,r,i=-1,u=n.length;if(1===arguments.length){for(;++i<u;)if(null!=(r=n[i])&&r>=r){e=r;break}for(;++i<u;)null!=(r=n[i])&&r>e&&(e=r)}else{for(;++i<u;)if(null!=(r=t.call(n,n[i],i))&&r>=r){e=r;break}for(;++i<u;)null!=(r=t.call(n,n[i],i))&&r>e&&(e=r)}return e},Ji.extent=function(n,t){var e,r,i,u=-1,o=n.length;if(1===arguments.length){for(;++u<o;)if(null!=(r=n[u])&&r>=r){e=i=r;break}for(;++u<o;)null!=(r=n[u])&&(e>r&&(e=r),r>i&&(i=r))}else{for(;++u<o;)if(null!=(r=t.call(n,n[u],u))&&r>=r){e=i=r;break}for(;++u<o;)null!=(r=t.call(n,n[u],u))&&(e>r&&(e=r),r>i&&(i=r))}return[e,i]},Ji.sum=function(n,t){var e,r=0,u=n.length,o=-1;if(1===arguments.length)for(;++o<u;)i(e=+n[o])&&(r+=e);else for(;++o<u;)i(e=+t.call(n,n[o],o))&&(r+=e);return r},Ji.mean=function(n,t){var e,u=0,o=n.length,a=-1,c=o;if(1===arguments.length)for(;++a<o;)i(e=r(n[a]))?u+=e:--c;else for(;++a<o;)i(e=r(t.call(n,n[a],a)))?u+=e:--c;return c?u/c:void 0},Ji.quantile=function(n,t){var e=(n.length-1)*t+1,r=Math.floor(e),i=+n[r-1],u=e-r;return u?i+u*(n[r]-i):i},Ji.median=function(n,t){var u,o=[],a=n.length,c=-1;if(1===arguments.length)for(;++c<a;)i(u=r(n[c]))&&o.push(u);else for(;++c<a;)i(u=r(t.call(n,n[c],c)))&&o.push(u);return o.length?Ji.quantile(o.sort(e),.5):void 0},Ji.variance=function(n,t){var e,u,o=n.length,a=0,c=0,l=-1,f=0;if(1===arguments.length)for(;++l<o;)i(e=r(n[l]))&&(c+=(u=e-a)*(e-(a+=u/++f)));else for(;++l<o;)i(e=r(t.call(n,n[l],l)))&&(c+=(u=e-a)*(e-(a+=u/++f)));return f>1?c/(f-1):void 0},Ji.deviation=function(){var n=Ji.variance.apply(this,arguments);return n?Math.sqrt(n):n};var uu=u(e);Ji.bisectLeft=uu.left,Ji.bisect=Ji.bisectRight=uu.right,Ji.bisector=function(n){return u(1===n.length?function(t,r){return e(n(t),r)}:n)},Ji.shuffle=function(n,t,e){(u=arguments.length)<3&&(e=n.length,2>u&&(t=0));for(var r,i,u=e-t;u;)i=Math.random()*u--|0,r=n[u+t],n[u+t]=n[i+t],n[i+t]=r;return n},Ji.permute=function(n,t){for(var e=t.length,r=new Array(e);e--;)r[e]=n[t[e]];return r},Ji.pairs=function(n){for(var t=0,e=n.length-1,r=n[0],i=new Array(0>e?0:e);e>t;)i[t]=[r,r=n[++t]];return i},Ji.zip=function(){if(!(r=arguments.length))return[];for(var n=-1,t=Ji.min(arguments,o),e=new Array(t);++n<t;)for(var r,i=-1,u=e[n]=new Array(r);++i<r;)u[i]=arguments[i][n];return e},Ji.transpose=function(n){return Ji.zip.apply(Ji,n)},Ji.keys=function(n){var t=[];for(var e in n)t.push(e);return t},Ji.values=function(n){var t=[];for(var e in n)t.push(n[e]);return t},Ji.entries=function(n){var t=[];for(var e in n)t.push({key:e,value:n[e]});return t},Ji.merge=function(n){for(var t,e,r,i=n.length,u=-1,o=0;++u<i;)o+=n[u].length;for(e=new Array(o);--i>=0;)for(t=(r=n[i]).length;--t>=0;)e[--o]=r[t];return e};var ou=Math.abs;Ji.range=function(n,t,e){if(arguments.length<3&&(e=1,arguments.length<2&&(t=n,n=0)),(t-n)/e==1/0)throw new Error("infinite range");var r,i=[],u=function(n){for(var t=1;n*t%1;)t*=10;return t}(ou(e)),o=-1;if(n*=u,t*=u,0>(e*=u))for(;(r=n+e*++o)>t;)i.push(r/u);else for(;(r=n+e*++o)<t;)i.push(r/u);return i},Ji.map=function(n,t){var e=new c;if(n instanceof c)n.forEach(function(n,t){e.set(n,t)});else if(Array.isArray(n)){var r,i=-1,u=n.length;if(1===arguments.length)for(;++i<u;)e.set(i,n[i]);else for(;++i<u;)e.set(t.call(n,r=n[i],i),r)}else for(var o in n)e.set(o,n[o]);return e};var au="__proto__",cu="\0";a(c,{has:s,get:function(n){return this._[l(n)]},set:function(n,t){return this._[l(n)]=t},remove:h,keys:p,values:function(){var n=[];for(var t in this._)n.push(this._[t]);return n},entries:function(){var n=[];for(var t in this._)n.push({key:f(t),value:this._[t]});return n},size:g,empty:v,forEach:function(n){for(var t in this._)n.call(this,f(t),this._[t])}}),Ji.nest=function(){function n(u,o,a){if(a>=i.length)return e?e.call(r,o):t?o.sort(t):o;for(var l,f,s,h,p=-1,g=o.length,v=i[a++],d=new c;++p<g;)(h=d.get(l=v(f=o[p])))?h.push(f):d.set(l,[f]);return u?(f=u(),s=function(t,e){f.set(t,n(u,e,a))}):(f={},s=function(t,e){f[t]=n(u,e,a)}),d.forEach(s),f}var t,e,r={},i=[],u=[];return r.map=function(t,e){return n(e,t,0)},r.entries=function(t){return function n(t,e){if(e>=i.length)return t;var r=[],o=u[e++];return t.forEach(function(t,i){r.push({key:t,values:n(i,e)})}),o?r.sort(function(n,t){return o(n.key,t.key)}):r}(n(Ji.map,t,0),0)},r.key=function(n){return i.push(n),r},r.sortKeys=function(n){return u[i.length-1]=n,r},r.sortValues=function(n){return t=n,r},r.rollup=function(n){return e=n,r},r},Ji.set=function(n){var t=new d;if(n)for(var e=0,r=n.length;r>e;++e)t.add(n[e]);return t},a(d,{has:s,add:function(n){return this._[l(n+="")]=!0,n},remove:h,values:p,size:g,empty:v,forEach:function(n){for(var t in this._)n.call(this,f(t))}}),Ji.behavior={},Ji.rebind=function(n,t){for(var e,r=1,i=arguments.length;++r<i;)n[e=arguments[r]]=m(n,t,t[e]);return n};var lu=["webkit","ms","moz","Moz","o","O"];Ji.dispatch=function(){for(var n=new b,t=-1,e=arguments.length;++t<e;)n[arguments[t]]=_(n);return n},b.prototype.on=function(n,t){var e=n.indexOf("."),r="";if(e>=0&&(r=n.slice(e+1),n=n.slice(0,e)),n)return arguments.length<2?this[n].on(r):this[n].on(r,t);if(2===arguments.length){if(null==t)for(n in this)this.hasOwnProperty(n)&&this[n].on(r,null);return this}},Ji.event=null,Ji.requote=function(n){return n.replace(fu,"\\$&")};var fu=/[\\\^\$\*\+\?\|\[\]\(\)\.\{\}]/g,su={}.__proto__?function(n,t){n.__proto__=t}:function(n,t){for(var e in t)n[e]=t[e]},hu=function(n,t){return t.querySelector(n)},pu=function(n,t){return t.querySelectorAll(n)},gu=function(n,t){var e=n.matches||n[M(n,"matchesSelector")];return(gu=function(n,t){return e.call(n,t)})(n,t)};"function"==typeof Sizzle&&(hu=function(n,t){return Sizzle(n,t)[0]||null},pu=Sizzle,gu=Sizzle.matchesSelector),Ji.selection=function(){return Ji.select(Qi.documentElement)};var vu=Ji.selection.prototype=[];vu.select=function(n){var t,e,r,i,u=[];n=E(n);for(var o=-1,a=this.length;++o<a;){u.push(t=[]),t.parentNode=(r=this[o]).parentNode;for(var c=-1,l=r.length;++c<l;)(i=r[c])?(t.push(e=n.call(i,i.__data__,c,o)),e&&"__data__"in i&&(e.__data__=i.__data__)):t.push(null)}return N(u)},vu.selectAll=function(n){var t,e,r=[];n=A(n);for(var i=-1,u=this.length;++i<u;)for(var o=this[i],a=-1,c=o.length;++a<c;)(e=o[a])&&(r.push(t=Ki(n.call(e,e.__data__,a,i))),t.parentNode=e);return N(r)};var du={svg:"http://www.w3.org/2000/svg",xhtml:"http://www.w3.org/1999/xhtml",xlink:"http://www.w3.org/1999/xlink",xml:"http://www.w3.org/XML/1998/namespace",xmlns:"http://www.w3.org/2000/xmlns/"};Ji.ns={prefix:du,qualify:function(n){var t=n.indexOf(":"),e=n;return t>=0&&(e=n.slice(0,t),n=n.slice(t+1)),du.hasOwnProperty(e)?{space:du[e],local:n}:n}},vu.attr=function(n,t){if(arguments.length<2){if("string"==typeof n){var e=this.node();return(n=Ji.ns.qualify(n)).local?e.getAttributeNS(n.space,n.local):e.getAttribute(n)}for(t in n)this.each(C(t,n[t]));return this}return this.each(C(n,t))},vu.classed=function(n,t){if(arguments.length<2){if("string"==typeof n){var e=this.node(),r=(n=L(n)).length,i=-1;if(t=e.classList){for(;++i<r;)if(!t.contains(n[i]))return!1}else for(t=e.getAttribute("class");++i<r;)if(!q(n[i]).test(t))return!1;return!0}for(t in n)this.each(T(t,n[t]));return this}return this.each(T(n,t))},vu.style=function(n,e,r){var i=arguments.length;if(3>i){if("string"!=typeof n){for(r in 2>i&&(e=""),n)this.each(D(r,n[r],e));return this}if(2>i){var u=this.node();return t(u).getComputedStyle(u,null).getPropertyValue(n)}r=""}return this.each(D(n,e,r))},vu.property=function(n,t){if(arguments.length<2){if("string"==typeof n)return this.node()[n];for(t in n)this.each(P(t,n[t]));return this}return this.each(P(n,t))},vu.text=function(n){return arguments.length?this.each("function"==typeof n?function(){var t=n.apply(this,arguments);this.textContent=null==t?"":t}:null==n?function(){this.textContent=""}:function(){this.textContent=n}):this.node().textContent},vu.html=function(n){return arguments.length?this.each("function"==typeof n?function(){var t=n.apply(this,arguments);this.innerHTML=null==t?"":t}:null==n?function(){this.innerHTML=""}:function(){this.innerHTML=n}):this.node().innerHTML},vu.append=function(n){return n=U(n),this.select(function(){return this.appendChild(n.apply(this,arguments))})},vu.insert=function(n,t){return n=U(n),t=E(t),this.select(function(){return this.insertBefore(n.apply(this,arguments),t.apply(this,arguments)||null)})},vu.remove=function(){return this.each(j)},vu.data=function(n,t){function e(n,e){var r,i,u,o=n.length,s=e.length,h=Math.min(o,s),p=new Array(s),g=new Array(s),v=new Array(o);if(t){var d,y=new c,m=new Array(o);for(r=-1;++r<o;)y.has(d=t.call(i=n[r],i.__data__,r))?v[r]=i:y.set(d,i),m[r]=d;for(r=-1;++r<s;)(i=y.get(d=t.call(e,u=e[r],r)))?!0!==i&&(p[r]=i,i.__data__=u):g[r]=F(u),y.set(d,!0);for(r=-1;++r<o;)!0!==y.get(m[r])&&(v[r]=n[r])}else{for(r=-1;++r<h;)i=n[r],u=e[r],i?(i.__data__=u,p[r]=i):g[r]=F(u);for(;s>r;++r)g[r]=F(e[r]);for(;o>r;++r)v[r]=n[r]}g.update=p,g.parentNode=p.parentNode=v.parentNode=n.parentNode,a.push(g),l.push(p),f.push(v)}var r,i,u=-1,o=this.length;if(!arguments.length){for(n=new Array(o=(r=this[0]).length);++u<o;)(i=r[u])&&(n[u]=i.__data__);return n}var a=Y([]),l=N([]),f=N([]);if("function"==typeof n)for(;++u<o;)e(r=this[u],n.call(r,r.parentNode.__data__,u));else for(;++u<o;)e(r=this[u],n);return l.enter=function(){return a},l.exit=function(){return f},l},vu.datum=function(n){return arguments.length?this.property("__data__",n):this.property("__data__")},vu.filter=function(n){var t,e,r,i=[];"function"!=typeof n&&(n=H(n));for(var u=0,o=this.length;o>u;u++){i.push(t=[]),t.parentNode=(e=this[u]).parentNode;for(var a=0,c=e.length;c>a;a++)(r=e[a])&&n.call(r,r.__data__,a,u)&&t.push(r)}return N(i)},vu.order=function(){for(var n=-1,t=this.length;++n<t;)for(var e,r=this[n],i=r.length-1,u=r[i];--i>=0;)(e=r[i])&&(u&&u!==e.nextSibling&&u.parentNode.insertBefore(e,u),u=e);return this},vu.sort=function(n){n=O.apply(this,arguments);for(var t=-1,e=this.length;++t<e;)this[t].sort(n);return this.order()},vu.each=function(n){return I(this,function(t,e,r){n.call(t,t.__data__,e,r)})},vu.call=function(n){var t=Ki(arguments);return n.apply(t[0]=this,t),this},vu.empty=function(){return!this.node()},vu.node=function(){for(var n=0,t=this.length;t>n;n++)for(var e=this[n],r=0,i=e.length;i>r;r++){var u=e[r];if(u)return u}return null},vu.size=function(){var n=0;return I(this,function(){++n}),n};var yu=[];Ji.selection.enter=Y,Ji.selection.enter.prototype=yu,yu.append=vu.append,yu.empty=vu.empty,yu.node=vu.node,yu.call=vu.call,yu.size=vu.size,yu.select=function(n){for(var t,e,r,i,u,o=[],a=-1,c=this.length;++a<c;){r=(i=this[a]).update,o.push(t=[]),t.parentNode=i.parentNode;for(var l=-1,f=i.length;++l<f;)(u=i[l])?(t.push(r[l]=e=n.call(i.parentNode,u.__data__,l,a)),e.__data__=u.__data__):t.push(null)}return N(o)},yu.insert=function(n,t){return arguments.length<2&&(t=function(n){var t,e;return function(r,i,u){var o,a=n[u].update,c=a.length;for(u!=e&&(e=u,t=0),i>=t&&(t=i+1);!(o=a[t])&&++t<c;);return o}}(this)),vu.insert.call(this,n,t)},Ji.select=function(t){var e;return"string"==typeof t?(e=[hu(t,Qi)]).parentNode=Qi.documentElement:(e=[t]).parentNode=n(t),N([e])},Ji.selectAll=function(n){var t;return"string"==typeof n?(t=Ki(pu(n,Qi))).parentNode=Qi.documentElement:(t=n).parentNode=null,N([t])},vu.on=function(n,t,e){var r=arguments.length;if(3>r){if("string"!=typeof n){for(e in 2>r&&(t=!1),n)this.each(Z(e,n[e],t));return this}if(2>r)return(r=this.node()["__on"+n])&&r._;e=!1}return this.each(Z(n,t,e))};var mu=Ji.map({mouseenter:"mouseover",mouseleave:"mouseout"});Qi&&mu.forEach(function(n){"on"+n in Qi&&mu.remove(n)});var Mu,xu=0;Ji.mouse=function(n){return B(n,S())};var bu=this.navigator&&/WebKit/.test(this.navigator.userAgent)?-1:0;Ji.touch=function(n,t,e){if(arguments.length<3&&(e=t,t=S().changedTouches),t)for(var r,i=0,u=t.length;u>i;++i)if((r=t[i]).identifier===e)return B(n,r)},Ji.behavior.drag=function(){function n(){this.on("mousedown.drag",u).on("touchstart.drag",o)}function e(n,t,e,u,o){return function(){var a,c=this,l=Ji.event.target,f=c.parentNode,s=r.of(c,arguments),h=0,p=n(),g=".drag"+(null==p?"":"-"+p),v=Ji.select(e(l)).on(u+g,function(){var n,e,r=t(f,p);r&&(n=r[0]-y[0],e=r[1]-y[1],h|=n|e,y=r,s({type:"drag",x:r[0]+a[0],y:r[1]+a[1],dx:n,dy:e}))}).on(o+g,function(){t(f,p)&&(v.on(u+g,null).on(o+g,null),d(h&&Ji.event.target===l),s({type:"dragend"}))}),d=$(l),y=t(f,p);i?a=[(a=i.apply(c,arguments)).x-y[0],a.y-y[1]]:a=[0,0],s({type:"dragstart"})}}var r=k(n,"drag","dragstart","dragend"),i=null,u=e(x,Ji.mouse,t,"mousemove","mouseup"),o=e(W,Ji.touch,y,"touchmove","touchend");return n.origin=function(t){return arguments.length?(i=t,n):i},Ji.rebind(n,r,"on")},Ji.touches=function(n,t){return arguments.length<2&&(t=S().touches),t?Ki(t).map(function(t){var e=B(n,t);return e.identifier=t.identifier,e}):[]};var _u=1e-6,wu=_u*_u,Su=Math.PI,ku=2*Su,Nu=ku-_u,Eu=Su/2,Au=Su/180,Cu=180/Su,zu=Math.SQRT2,qu=2;Ji.interpolateZoom=function(n,t){function e(n){var t=n*y;if(d){var e=nn(v),o=u/(qu*h)*(e*function(n){return((n=Math.exp(2*n))-1)/(n+1)}(zu*t+v)-function(n){return((n=Math.exp(n))-1/n)/2}(v));return[r+o*l,i+o*f,u*e/nn(zu*t+v)]}return[r+n*l,i+n*f,u*Math.exp(zu*t)]}var r=n[0],i=n[1],u=n[2],o=t[0],a=t[1],c=t[2],l=o-r,f=a-i,s=l*l+f*f,h=Math.sqrt(s),p=(c*c-u*u+4*s)/(2*u*qu*h),g=(c*c-u*u-4*s)/(2*c*qu*h),v=Math.log(Math.sqrt(p*p+1)-p),d=Math.log(Math.sqrt(g*g+1)-g)-v,y=(d||Math.log(c/u))/zu;return e.duration=1e3*y,e},Ji.behavior.zoom=function(){function n(n){n.on(z,f).on(Tu+".zoom",h).on("dblclick.zoom",p).on(T,s)}function e(n){return[(n[0]-S.x)/S.k,(n[1]-S.y)/S.k]}function r(n){S.k=Math.max(E[0],Math.min(E[1],n))}function i(n,t){t=function(n){return[n[0]*S.k+S.x,n[1]*S.k+S.y]}(t),S.x+=n[0]-t[0],S.y+=n[1]-t[1]}function u(t,e,u,o){t.__chart__={x:S.x,y:S.y,k:S.k},r(Math.pow(2,o)),i(v=e,u),t=Ji.select(t),A>0&&(t=t.transition().duration(A)),t.call(n.event)}function o(){x&&x.domain(M.range().map(function(n){return(n-S.x)/S.k}).map(M.invert)),_&&_.domain(b.range().map(function(n){return(n-S.y)/S.k}).map(b.invert))}function a(n){C++||n({type:"zoomstart"})}function c(n){o(),n({type:"zoom",scale:S.k,translate:[S.x,S.y]})}function l(n){--C||(n({type:"zoomend"}),v=null)}function f(){var n=this,r=Ji.event.target,u=R.of(n,arguments),o=0,f=Ji.select(t(n)).on(q,function(){o=1,i(Ji.mouse(n),s),c(u)}).on(L,function(){f.on(q,null).on(L,null),h(o&&Ji.event.target===r),l(u)}),s=e(Ji.mouse(n)),h=$(n);Aa.call(n),a(u)}function s(){function n(){var n=Ji.touches(g);return p=S.k,n.forEach(function(n){n.identifier in d&&(d[n.identifier]=e(n))}),n}function t(){var t=Ji.event.target;Ji.select(t).on(x,o).on(b,h),_.push(t);for(var e=Ji.event.changedTouches,r=0,i=e.length;i>r;++r)d[e[r].identifier]=null;var a=n(),c=Date.now();if(1===a.length){if(500>c-m){var l=a[0];u(g,l,d[l.identifier],Math.floor(Math.log(S.k)/Math.LN2)+1),w()}m=c}else if(a.length>1){l=a[0];var f=a[1],s=l[0]-f[0],p=l[1]-f[1];y=s*s+p*p}}function o(){var n,t,e,u,o=Ji.touches(g);Aa.call(g);for(var a=0,l=o.length;l>a;++a,u=null)if(e=o[a],u=d[e.identifier]){if(t)break;n=e,t=u}if(u){var f=(f=e[0]-n[0])*f+(f=e[1]-n[1])*f,s=y&&Math.sqrt(f/y);n=[(n[0]+e[0])/2,(n[1]+e[1])/2],t=[(t[0]+u[0])/2,(t[1]+u[1])/2],r(s*p)}m=null,i(n,t),c(v)}function h(){if(Ji.event.touches.length){for(var t=Ji.event.changedTouches,e=0,r=t.length;r>e;++e)delete d[t[e].identifier];for(var i in d)return void n()}Ji.selectAll(_).on(M,null),k.on(z,f).on(T,s),N(),l(v)}var p,g=this,v=R.of(g,arguments),d={},y=0,M=".zoom-"+Ji.event.changedTouches[0].identifier,x="touchmove"+M,b="touchend"+M,_=[],k=Ji.select(g),N=$(g);t(),a(v),k.on(z,null).on(T,t)}function h(){var n=R.of(this,arguments);y?clearTimeout(y):(Aa.call(this),g=e(v=d||Ji.mouse(this)),a(n)),y=setTimeout(function(){y=null,l(n)},50),w(),r(Math.pow(2,.002*Lu())*S.k),i(v,g),c(n)}function p(){var n=Ji.mouse(this),t=Math.log(S.k)/Math.LN2;u(this,n,e(n),Ji.event.shiftKey?Math.ceil(t)-1:Math.floor(t)+1)}var g,v,d,y,m,M,x,b,_,S={x:0,y:0,k:1},N=[960,500],E=Ru,A=250,C=0,z="mousedown.zoom",q="mousemove.zoom",L="mouseup.zoom",T="touchstart.zoom",R=k(n,"zoomstart","zoom","zoomend");return Tu||(Tu="onwheel"in Qi?(Lu=function(){return-Ji.event.deltaY*(Ji.event.deltaMode?120:1)},"wheel"):"onmousewheel"in Qi?(Lu=function(){return Ji.event.wheelDelta},"mousewheel"):(Lu=function(){return-Ji.event.detail},"MozMousePixelScroll")),n.event=function(n){n.each(function(){var n=R.of(this,arguments),t=S;Na?Ji.select(this).transition().each("start.zoom",function(){S=this.__chart__||{x:0,y:0,k:1},a(n)}).tween("zoom:zoom",function(){var e=N[0],r=N[1],i=v?v[0]:e/2,u=v?v[1]:r/2,o=Ji.interpolateZoom([(i-S.x)/S.k,(u-S.y)/S.k,e/S.k],[(i-t.x)/t.k,(u-t.y)/t.k,e/t.k]);return function(t){var r=o(t),a=e/r[2];this.__chart__=S={x:i-r[0]*a,y:u-r[1]*a,k:a},c(n)}}).each("interrupt.zoom",function(){l(n)}).each("end.zoom",function(){l(n)}):(this.__chart__=S,a(n),c(n),l(n))})},n.translate=function(t){return arguments.length?(S={x:+t[0],y:+t[1],k:S.k},o(),n):[S.x,S.y]},n.scale=function(t){return arguments.length?(S={x:S.x,y:S.y,k:+t},o(),n):S.k},n.scaleExtent=function(t){return arguments.length?(E=null==t?Ru:[+t[0],+t[1]],n):E},n.center=function(t){return arguments.length?(d=t&&[+t[0],+t[1]],n):d},n.size=function(t){return arguments.length?(N=t&&[+t[0],+t[1]],n):N},n.duration=function(t){return arguments.length?(A=+t,n):A},n.x=function(t){return arguments.length?(x=t,M=t.copy(),S={x:0,y:0,k:1},n):x},n.y=function(t){return arguments.length?(_=t,b=t.copy(),S={x:0,y:0,k:1},n):_},Ji.rebind(n,R,"on")};var Lu,Tu,Ru=[0,1/0];Ji.color=en,en.prototype.toString=function(){return this.rgb()+""},Ji.hsl=rn;var Du=rn.prototype=new en;Du.brighter=function(n){return n=Math.pow(.7,arguments.length?n:1),new rn(this.h,this.s,this.l/n)},Du.darker=function(n){return n=Math.pow(.7,arguments.length?n:1),new rn(this.h,this.s,n*this.l)},Du.rgb=function(){return un(this.h,this.s,this.l)},Ji.hcl=on;var Pu=on.prototype=new en;Pu.brighter=function(n){return new on(this.h,this.c,Math.min(100,this.l+Uu*(arguments.length?n:1)))},Pu.darker=function(n){return new on(this.h,this.c,Math.max(0,this.l-Uu*(arguments.length?n:1)))},Pu.rgb=function(){return an(this.h,this.c,this.l).rgb()},Ji.lab=cn;var Uu=18,ju=.95047,Fu=1,Hu=1.08883,Ou=cn.prototype=new en;Ou.brighter=function(n){return new cn(Math.min(100,this.l+Uu*(arguments.length?n:1)),this.a,this.b)},Ou.darker=function(n){return new cn(Math.max(0,this.l-Uu*(arguments.length?n:1)),this.a,this.b)},Ou.rgb=function(){return ln(this.l,this.a,this.b)},Ji.rgb=gn;var Iu=gn.prototype=new en;Iu.brighter=function(n){n=Math.pow(.7,arguments.length?n:1);var t=this.r,e=this.g,r=this.b,i=30;return t||e||r?(t&&i>t&&(t=i),e&&i>e&&(e=i),r&&i>r&&(r=i),new gn(Math.min(255,t/n),Math.min(255,e/n),Math.min(255,r/n))):new gn(i,i,i)},Iu.darker=function(n){return new gn((n=Math.pow(.7,arguments.length?n:1))*this.r,n*this.g,n*this.b)},Iu.hsl=function(){return Mn(this.r,this.g,this.b)},Iu.toString=function(){return"#"+yn(this.r)+yn(this.g)+yn(this.b)};var Yu=Ji.map({aliceblue:15792383,antiquewhite:16444375,aqua:65535,aquamarine:8388564,azure:15794175,beige:16119260,bisque:16770244,black:0,blanchedalmond:16772045,blue:255,blueviolet:9055202,brown:10824234,burlywood:14596231,cadetblue:6266528,chartreuse:8388352,chocolate:13789470,coral:16744272,cornflowerblue:6591981,cornsilk:16775388,crimson:14423100,cyan:65535,darkblue:139,darkcyan:35723,darkgoldenrod:12092939,darkgray:11119017,darkgreen:25600,darkgrey:11119017,darkkhaki:12433259,darkmagenta:9109643,darkolivegreen:5597999,darkorange:16747520,darkorchid:10040012,darkred:9109504,darksalmon:15308410,darkseagreen:9419919,darkslateblue:4734347,darkslategray:3100495,darkslategrey:3100495,darkturquoise:52945,darkviolet:9699539,deeppink:16716947,deepskyblue:49151,dimgray:6908265,dimgrey:6908265,dodgerblue:2003199,firebrick:11674146,floralwhite:16775920,forestgreen:2263842,fuchsia:16711935,gainsboro:14474460,ghostwhite:16316671,gold:16766720,goldenrod:14329120,gray:8421504,green:32768,greenyellow:11403055,grey:8421504,honeydew:15794160,hotpink:16738740,indianred:13458524,indigo:4915330,ivory:16777200,khaki:15787660,lavender:15132410,lavenderblush:16773365,lawngreen:8190976,lemonchiffon:16775885,lightblue:11393254,lightcoral:15761536,lightcyan:14745599,lightgoldenrodyellow:16448210,lightgray:13882323,lightgreen:9498256,lightgrey:13882323,lightpink:16758465,lightsalmon:16752762,lightseagreen:2142890,lightskyblue:8900346,lightslategray:7833753,lightslategrey:7833753,lightsteelblue:11584734,lightyellow:16777184,lime:65280,limegreen:3329330,linen:16445670,magenta:16711935,maroon:8388608,mediumaquamarine:6737322,mediumblue:205,mediumorchid:12211667,mediumpurple:9662683,mediumseagreen:3978097,mediumslateblue:8087790,mediumspringgreen:64154,mediumturquoise:4772300,mediumvioletred:13047173,midnightblue:1644912,mintcream:16121850,mistyrose:16770273,moccasin:16770229,navajowhite:16768685,navy:128,oldlace:16643558,olive:8421376,olivedrab:7048739,orange:16753920,orangered:16729344,orchid:14315734,palegoldenrod:15657130,palegreen:10025880,paleturquoise:11529966,palevioletred:14381203,papayawhip:16773077,peachpuff:16767673,peru:13468991,pink:16761035,plum:14524637,powderblue:11591910,purple:8388736,rebeccapurple:6697881,red:16711680,rosybrown:12357519,royalblue:4286945,saddlebrown:9127187,salmon:16416882,sandybrown:16032864,seagreen:3050327,seashell:16774638,sienna:10506797,silver:12632256,skyblue:8900331,slateblue:6970061,slategray:7372944,slategrey:7372944,snow:16775930,springgreen:65407,steelblue:4620980,tan:13808780,teal:32896,thistle:14204888,tomato:16737095,turquoise:4251856,violet:15631086,wheat:16113331,white:16777215,whitesmoke:16119285,yellow:16776960,yellowgreen:10145074});Yu.forEach(function(n,t){Yu.set(n,vn(t))}),Ji.functor=wn,Ji.xhr=Sn(y),Ji.dsv=function(n,t){function e(n,e,u){arguments.length<3&&(u=e,e=null);var o=kn(n,t,null==e?r:i(e),u);return o.row=function(n){return arguments.length?o.response(null==(e=n)?r:i(n)):e},o}function r(n){return e.parse(n.responseText)}function i(n){return function(t){return e.parse(t.responseText,n)}}function u(t){return t.map(o).join(n)}function o(n){return a.test(n)?'"'+n.replace(/\"/g,'""')+'"':n}var a=new RegExp('["'+n+"\n]"),c=n.charCodeAt(0);return e.parse=function(n,t){var r;return e.parseRows(n,function(n,e){if(r)return r(n,e-1);var i=new Function("d","return {"+n.map(function(n,t){return JSON.stringify(n)+": d["+t+"]"}).join(",")+"}");r=t?function(n,e){return t(i(n),e)}:i})},e.parseRows=function(n,t){function e(){if(f>=l)return o;if(i)return i=!1,u;var t=f;if(34===n.charCodeAt(t)){for(var e=t;e++<l;)if(34===n.charCodeAt(e)){if(34!==n.charCodeAt(e+1))break;++e}return f=e+2,13===(r=n.charCodeAt(e+1))?(i=!0,10===n.charCodeAt(e+2)&&++f):10===r&&(i=!0),n.slice(t+1,e).replace(/""/g,'"')}for(;l>f;){var r,a=1;if(10===(r=n.charCodeAt(f++)))i=!0;else if(13===r)i=!0,10===n.charCodeAt(f)&&(++f,++a);else if(r!==c)continue;return n.slice(t,f-a)}return n.slice(t)}for(var r,i,u={},o={},a=[],l=n.length,f=0,s=0;(r=e())!==o;){for(var h=[];r!==u&&r!==o;)h.push(r),r=e();t&&null==(h=t(h,s++))||a.push(h)}return a},e.format=function(t){if(Array.isArray(t[0]))return e.formatRows(t);var r=new d,i=[];return t.forEach(function(n){for(var t in n)r.has(t)||i.push(r.add(t))}),[i.map(o).join(n)].concat(t.map(function(t){return i.map(function(n){return o(t[n])}).join(n)})).join("\n")},e.formatRows=function(n){return n.map(u).join("\n")},e},Ji.csv=Ji.dsv(",","text/csv"),Ji.tsv=Ji.dsv("\t","text/tab-separated-values");var Zu,Vu,Xu,$u,Bu,Wu=this[M(this,"requestAnimationFrame")]||function(n){setTimeout(n,17)};Ji.timer=function(n,t,e){var r=arguments.length;2>r&&(t=0),3>r&&(e=Date.now());var i={c:n,t:e+t,f:!1,n:null};Vu?Vu.n=i:Zu=i,Vu=i,Xu||($u=clearTimeout($u),Xu=1,Wu(Nn))},Ji.timer.flush=function(){En(),An()},Ji.round=function(n,t){return t?Math.round(n*(t=Math.pow(10,t)))/t:Math.round(n)};var Ju=["y","z","a","f","p","n","µ","m","","k","M","G","T","P","E","Z","Y"].map(function(n,t){var e=Math.pow(10,3*ou(8-t));return{scale:t>8?function(n){return n/e}:function(n){return n*e},symbol:n}});Ji.formatPrefix=function(n,t){var e=0;return n&&(0>n&&(n*=-1),t&&(n=Ji.round(n,Cn(n,t))),e=1+Math.floor(1e-12+Math.log(n)/Math.LN10),e=Math.max(-24,Math.min(24,3*Math.floor((e-1)/3)))),Ju[8+e/3]};var Gu=/(?:([^{])?([<>=^]))?([+\- ])?([$#])?(0)?(\d+)?(,)?(\.-?\d+)?([a-z%])?/i,Ku=Ji.map({b:function(n){return n.toString(2)},c:function(n){return String.fromCharCode(n)},o:function(n){return n.toString(8)},x:function(n){return n.toString(16)},X:function(n){return n.toString(16).toUpperCase()},g:function(n,t){return n.toPrecision(t)},e:function(n,t){return n.toExponential(t)},f:function(n,t){return n.toFixed(t)},r:function(n,t){return(n=Ji.round(n,Cn(n,t))).toFixed(Math.max(0,Math.min(20,Cn(n*(1+1e-15),t))))}}),Qu=Ji.time={},no=Date;Ln.prototype={getDate:function(){return this._.getUTCDate()},getDay:function(){return this._.getUTCDay()},getFullYear:function(){return this._.getUTCFullYear()},getHours:function(){return this._.getUTCHours()},getMilliseconds:function(){return this._.getUTCMilliseconds()},getMinutes:function(){return this._.getUTCMinutes()},getMonth:function(){return this._.getUTCMonth()},getSeconds:function(){return this._.getUTCSeconds()},getTime:function(){return this._.getTime()},getTimezoneOffset:function(){return 0},valueOf:function(){return this._.valueOf()},setDate:function(){to.setUTCDate.apply(this._,arguments)},setDay:function(){to.setUTCDay.apply(this._,arguments)},setFullYear:function(){to.setUTCFullYear.apply(this._,arguments)},setHours:function(){to.setUTCHours.apply(this._,arguments)},setMilliseconds:function(){to.setUTCMilliseconds.apply(this._,arguments)},setMinutes:function(){to.setUTCMinutes.apply(this._,arguments)},setMonth:function(){to.setUTCMonth.apply(this._,arguments)},setSeconds:function(){to.setUTCSeconds.apply(this._,arguments)},setTime:function(){to.setTime.apply(this._,arguments)}};var to=Date.prototype;Qu.year=Tn(function(n){return(n=Qu.day(n)).setMonth(0,1),n},function(n,t){n.setFullYear(n.getFullYear()+t)},function(n){return n.getFullYear()}),Qu.years=Qu.year.range,Qu.years.utc=Qu.year.utc.range,Qu.day=Tn(function(n){var t=new no(2e3,0);return t.setFullYear(n.getFullYear(),n.getMonth(),n.getDate()),t},function(n,t){n.setDate(n.getDate()+t)},function(n){return n.getDate()-1}),Qu.days=Qu.day.range,Qu.days.utc=Qu.day.utc.range,Qu.dayOfYear=function(n){var t=Qu.year(n);return Math.floor((n-t-6e4*(n.getTimezoneOffset()-t.getTimezoneOffset()))/864e5)},["sunday","monday","tuesday","wednesday","thursday","friday","saturday"].forEach(function(n,t){t=7-t;var e=Qu[n]=Tn(function(n){return(n=Qu.day(n)).setDate(n.getDate()-(n.getDay()+t)%7),n},function(n,t){n.setDate(n.getDate()+7*Math.floor(t))},function(n){var e=Qu.year(n).getDay();return Math.floor((Qu.dayOfYear(n)+(e+t)%7)/7)-(e!==t)});Qu[n+"s"]=e.range,Qu[n+"s"].utc=e.utc.range,Qu[n+"OfYear"]=function(n){var e=Qu.year(n).getDay();return Math.floor((Qu.dayOfYear(n)+(e+t)%7)/7)}}),Qu.week=Qu.sunday,Qu.weeks=Qu.sunday.range,Qu.weeks.utc=Qu.sunday.utc.range,Qu.weekOfYear=Qu.sundayOfYear;var eo={"-":"",_:" ",0:"0"},ro=/^\s*\d+/,io=/^%/;Ji.locale=function(n){return{numberFormat:zn(n),timeFormat:Dn(n)}};var uo=Ji.locale({decimal:".",thousands:",",grouping:[3],currency:["$",""],dateTime:"%a %b %e %X %Y",date:"%m/%d/%Y",time:"%H:%M:%S",periods:["AM","PM"],days:["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"],shortDays:["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],months:["January","February","March","April","May","June","July","August","September","October","November","December"],shortMonths:["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]});Ji.format=uo.numberFormat,Ji.geo={},tt.prototype={s:0,t:0,add:function(n){et(n,this.t,oo),et(oo.s,this.s,this),this.s?this.t+=oo.t:this.s=oo.t},reset:function(){this.s=this.t=0},valueOf:function(){return this.s}};var oo=new tt;Ji.geo.stream=function(n,t){n&&ao.hasOwnProperty(n.type)?ao[n.type](n,t):rt(n,t)};var ao={Feature:function(n,t){rt(n.geometry,t)},FeatureCollection:function(n,t){for(var e=n.features,r=-1,i=e.length;++r<i;)rt(e[r].geometry,t)}},co={Sphere:function(n,t){t.sphere()},Point:function(n,t){n=n.coordinates,t.point(n[0],n[1],n[2])},MultiPoint:function(n,t){for(var e=n.coordinates,r=-1,i=e.length;++r<i;)n=e[r],t.point(n[0],n[1],n[2])},LineString:function(n,t){it(n.coordinates,t,0)},MultiLineString:function(n,t){for(var e=n.coordinates,r=-1,i=e.length;++r<i;)it(e[r],t,0)},Polygon:function(n,t){ut(n.coordinates,t)},MultiPolygon:function(n,t){for(var e=n.coordinates,r=-1,i=e.length;++r<i;)ut(e[r],t)},GeometryCollection:function(n,t){for(var e=n.geometries,r=-1,i=e.length;++r<i;)rt(e[r],t)}};Ji.geo.area=function(n){return lo=0,Ji.geo.stream(n,so),lo};var lo,fo=new tt,so={sphere:function(){lo+=4*Su},point:x,lineStart:x,lineEnd:x,polygonStart:function(){fo.reset(),so.lineStart=ot},polygonEnd:function(){var n=2*fo;lo+=0>n?4*Su+n:n,so.lineStart=so.lineEnd=so.point=x}};Ji.geo.bounds=function(){function n(n,t){M.push(x=[f=n,h=n]),s>t&&(s=t),t>p&&(p=t)}function t(t,e){var r=at([t*Au,e*Au]);if(y){var i=lt(y,r),u=lt([i[1],-i[0],0],i);ht(u),u=pt(u);var o=t-g,c=o>0?1:-1,l=u[0]*Cu*c,v=ou(o)>180;if(v^(l>c*g&&c*t>l))(d=u[1]*Cu)>p&&(p=d);else if(v^((l=(l+360)%360-180)>c*g&&c*t>l)){var d=-u[1]*Cu;s>d&&(s=d)}else s>e&&(s=e),e>p&&(p=e);v?g>t?a(f,t)>a(f,h)&&(h=t):a(t,h)>a(f,h)&&(f=t):h>=f?(f>t&&(f=t),t>h&&(h=t)):t>g?a(f,t)>a(f,h)&&(h=t):a(t,h)>a(f,h)&&(f=t)}else n(t,e);y=r,g=t}function e(){b.point=t}function r(){x[0]=f,x[1]=h,b.point=n,y=null}function i(n,e){if(y){var r=n-g;m+=ou(r)>180?r+(r>0?360:-360):r}else v=n,d=e;so.point(n,e),t(n,e)}function u(){so.lineStart()}function o(){i(v,d),so.lineEnd(),ou(m)>_u&&(f=-(h=180)),x[0]=f,x[1]=h,y=null}function a(n,t){return(t-=n)<0?t+360:t}function c(n,t){return n[0]-t[0]}function l(n,t){return t[0]<=t[1]?t[0]<=n&&n<=t[1]:n<t[0]||t[1]<n}var f,s,h,p,g,v,d,y,m,M,x,b={point:n,lineStart:e,lineEnd:r,polygonStart:function(){b.point=i,b.lineStart=u,b.lineEnd=o,m=0,so.polygonStart()},polygonEnd:function(){so.polygonEnd(),b.point=n,b.lineStart=e,b.lineEnd=r,0>fo?(f=-(h=180),s=-(p=90)):m>_u?p=90:-_u>m&&(s=-90),x[0]=f,x[1]=h}};return function(n){if(p=h=-(f=s=1/0),M=[],Ji.geo.stream(n,b),u=M.length){M.sort(c);for(var t=1,e=[g=M[0]];u>t;++t)l((i=M[t])[0],g)||l(i[1],g)?(a(g[0],i[1])>a(g[0],g[1])&&(g[1]=i[1]),a(i[0],g[1])>a(g[0],g[1])&&(g[0]=i[0])):e.push(g=i);for(var r,i,u,o=-1/0,g=(t=0,e[u=e.length-1]);u>=t;g=i,++t)i=e[t],(r=a(g[1],i[0]))>o&&(o=r,f=i[0],h=g[1])}return M=x=null,1/0===f||1/0===s?[[NaN,NaN],[NaN,NaN]]:[[f,s],[h,p]]}}(),Ji.geo.centroid=function(n){ho=po=go=vo=yo=mo=Mo=xo=bo=_o=wo=0,Ji.geo.stream(n,So);var t=bo,e=_o,r=wo,i=t*t+e*e+r*r;return wu>i&&(t=mo,e=Mo,r=xo,_u>po&&(t=go,e=vo,r=yo),wu>(i=t*t+e*e+r*r))?[NaN,NaN]:[Math.atan2(e,t)*Cu,Q(r/Math.sqrt(i))*Cu]};var ho,po,go,vo,yo,mo,Mo,xo,bo,_o,wo,So={sphere:x,point:vt,lineStart:yt,lineEnd:mt,polygonStart:function(){So.lineStart=Mt},polygonEnd:function(){So.lineStart=yt}},ko=kt(bt,function(n){var t,e=NaN,r=NaN,i=NaN;return{lineStart:function(){n.lineStart(),t=1},point:function(u,o){var a=u>0?Su:-Su,c=ou(u-e);ou(c-Su)<_u?(n.point(e,r=(r+o)/2>0?Eu:-Eu),n.point(i,r),n.lineEnd(),n.lineStart(),n.point(a,r),n.point(u,r),t=0):i!==a&&c>=Su&&(ou(e-i)<_u&&(e-=i*_u),ou(u-a)<_u&&(u-=a*_u),r=function(n,t,e,r){var i,u,o=Math.sin(n-e);return ou(o)>_u?Math.atan((Math.sin(t)*(u=Math.cos(r))*Math.sin(e)-Math.sin(r)*(i=Math.cos(t))*Math.sin(n))/(i*u*o)):(t+r)/2}(e,r,u,o),n.point(i,r),n.lineEnd(),n.lineStart(),n.point(a,r),t=0),n.point(e=u,r=o),i=a},lineEnd:function(){n.lineEnd(),e=r=NaN},clean:function(){return 2-t}}},function(n,t,e,r){var i;if(null==n)i=e*Eu,r.point(-Su,i),r.point(0,i),r.point(Su,i),r.point(Su,0),r.point(Su,-i),r.point(0,-i),r.point(-Su,-i),r.point(-Su,0),r.point(-Su,i);else if(ou(n[0]-t[0])>_u){var u=n[0]<t[0]?Su:-Su;i=e*u/2,r.point(-u,i),r.point(0,i),r.point(u,i)}else r.point(t[0],t[1])},[-Su,-Su/2]),No=1e9;Ji.geo.clipExtent=function(){var n,t,e,r,i,u,o={stream:function(n){return i&&(i.valid=!1),(i=u(n)).valid=!0,i},extent:function(a){return arguments.length?(u=zt(n=+a[0][0],t=+a[0][1],e=+a[1][0],r=+a[1][1]),i&&(i.valid=!1,i=null),o):[[n,t],[e,r]]}};return o.extent([[0,0],[960,500]])},(Ji.geo.conicEqualArea=function(){return qt(Lt)}).raw=Lt,Ji.geo.albers=function(){return Ji.geo.conicEqualArea().rotate([96,0]).center([-.6,38.7]).parallels([29.5,45.5]).scale(1070)},Ji.geo.albersUsa=function(){function n(n){var u=n[0],o=n[1];return t=null,e(u,o),t||(r(u,o),t)||i(u,o),t}var t,e,r,i,u=Ji.geo.albers(),o=Ji.geo.conicEqualArea().rotate([154,0]).center([-2,58.5]).parallels([55,65]),a=Ji.geo.conicEqualArea().rotate([157,0]).center([-3,19.9]).parallels([8,18]),c={point:function(n,e){t=[n,e]}};return n.invert=function(n){var t=u.scale(),e=u.translate(),r=(n[0]-e[0])/t,i=(n[1]-e[1])/t;return(i>=.12&&.234>i&&r>=-.425&&-.214>r?o:i>=.166&&.234>i&&r>=-.214&&-.115>r?a:u).invert(n)},n.stream=function(n){var t=u.stream(n),e=o.stream(n),r=a.stream(n);return{point:function(n,i){t.point(n,i),e.point(n,i),r.point(n,i)},sphere:function(){t.sphere(),e.sphere(),r.sphere()},lineStart:function(){t.lineStart(),e.lineStart(),r.lineStart()},lineEnd:function(){t.lineEnd(),e.lineEnd(),r.lineEnd()},polygonStart:function(){t.polygonStart(),e.polygonStart(),r.polygonStart()},polygonEnd:function(){t.polygonEnd(),e.polygonEnd(),r.polygonEnd()}}},n.precision=function(t){return arguments.length?(u.precision(t),o.precision(t),a.precision(t),n):u.precision()},n.scale=function(t){return arguments.length?(u.scale(t),o.scale(.35*t),a.scale(t),n.translate(u.translate())):u.scale()},n.translate=function(t){if(!arguments.length)return u.translate();var l=u.scale(),f=+t[0],s=+t[1];return e=u.translate(t).clipExtent([[f-.455*l,s-.238*l],[f+.455*l,s+.238*l]]).stream(c).point,r=o.translate([f-.307*l,s+.201*l]).clipExtent([[f-.425*l+_u,s+.12*l+_u],[f-.214*l-_u,s+.234*l-_u]]).stream(c).point,i=a.translate([f-.205*l,s+.212*l]).clipExtent([[f-.214*l+_u,s+.166*l+_u],[f-.115*l-_u,s+.234*l-_u]]).stream(c).point,n},n.scale(1070)};var Eo,Ao,Co,zo,qo,Lo,To={point:x,lineStart:x,lineEnd:x,polygonStart:function(){Ao=0,To.lineStart=Tt},polygonEnd:function(){To.lineStart=To.lineEnd=To.point=x,Eo+=ou(Ao/2)}},Ro={point:function(n,t){Co>n&&(Co=n),n>qo&&(qo=n),zo>t&&(zo=t),t>Lo&&(Lo=t)},lineStart:x,lineEnd:x,polygonStart:x,polygonEnd:x},Do={point:Pt,lineStart:Ut,lineEnd:jt,polygonStart:function(){Do.lineStart=Ft},polygonEnd:function(){Do.point=Pt,Do.lineStart=Ut,Do.lineEnd=jt}};Ji.geo.path=function(){function n(n){return n&&("function"==typeof a&&u.pointRadius(+a.apply(this,arguments)),o&&o.valid||(o=i(u)),Ji.geo.stream(n,o)),u.result()}function t(){return o=null,n}var e,r,i,u,o,a=4.5;return n.area=function(n){return Eo=0,Ji.geo.stream(n,i(To)),Eo},n.centroid=function(n){return go=vo=yo=mo=Mo=xo=bo=_o=wo=0,Ji.geo.stream(n,i(Do)),wo?[bo/wo,_o/wo]:xo?[mo/xo,Mo/xo]:yo?[go/yo,vo/yo]:[NaN,NaN]},n.bounds=function(n){return qo=Lo=-(Co=zo=1/0),Ji.geo.stream(n,i(Ro)),[[Co,zo],[qo,Lo]]},n.projection=function(n){return arguments.length?(i=(e=n)?n.stream||function(n){var t=Ot(function(t,e){return n([t*Cu,e*Cu])});return function(n){return Xt(t(n))}}(n):y,t()):e},n.context=function(n){return arguments.length?(u=null==(r=n)?new Rt:new Ht(n),"function"!=typeof a&&u.pointRadius(a),t()):r},n.pointRadius=function(t){return arguments.length?(a="function"==typeof t?t:(u.pointRadius(+t),+t),n):a},n.projection(Ji.geo.albersUsa()).context(null)},Ji.geo.transform=function(n){return{stream:function(t){var e=new It(t);for(var r in n)e[r]=n[r];return e}}},It.prototype={point:function(n,t){this.stream.point(n,t)},sphere:function(){this.stream.sphere()},lineStart:function(){this.stream.lineStart()},lineEnd:function(){this.stream.lineEnd()},polygonStart:function(){this.stream.polygonStart()},polygonEnd:function(){this.stream.polygonEnd()}},Ji.geo.projection=Zt,Ji.geo.projectionMutator=Vt,(Ji.geo.equirectangular=function(){return Zt($t)}).raw=$t.invert=$t,Ji.geo.rotation=function(n){function t(t){return(t=n(t[0]*Au,t[1]*Au))[0]*=Cu,t[1]*=Cu,t}return n=Wt(n[0]%360*Au,n[1]*Au,n.length>2?n[2]*Au:0),t.invert=function(t){return(t=n.invert(t[0]*Au,t[1]*Au))[0]*=Cu,t[1]*=Cu,t},t},Bt.invert=$t,Ji.geo.circle=function(){function n(){var n="function"==typeof r?r.apply(this,arguments):r,t=Wt(-n[0]*Au,-n[1]*Au,0).invert,i=[];return e(null,null,1,{point:function(n,e){i.push(n=t(n,e)),n[0]*=Cu,n[1]*=Cu}}),{type:"Polygon",coordinates:[i]}}var t,e,r=[0,0],i=6;return n.origin=function(t){return arguments.length?(r=t,n):r},n.angle=function(r){return arguments.length?(e=Qt((t=+r)*Au,i*Au),n):t},n.precision=function(r){return arguments.length?(e=Qt(t*Au,(i=+r)*Au),n):i},n.angle(90)},Ji.geo.distance=function(n,t){var e,r=(t[0]-n[0])*Au,i=n[1]*Au,u=t[1]*Au,o=Math.sin(r),a=Math.cos(r),c=Math.sin(i),l=Math.cos(i),f=Math.sin(u),s=Math.cos(u);return Math.atan2(Math.sqrt((e=s*o)*e+(e=l*f-c*s*a)*e),c*f+l*s*a)},Ji.geo.graticule=function(){function n(){return{type:"MultiLineString",coordinates:t()}}function t(){return Ji.range(Math.ceil(u/d)*d,i,d).map(h).concat(Ji.range(Math.ceil(l/y)*y,c,y).map(p)).concat(Ji.range(Math.ceil(r/g)*g,e,g).filter(function(n){return ou(n%d)>_u}).map(f)).concat(Ji.range(Math.ceil(a/v)*v,o,v).filter(function(n){return ou(n%y)>_u}).map(s))}var e,r,i,u,o,a,c,l,f,s,h,p,g=10,v=g,d=90,y=360,m=2.5;return n.lines=function(){return t().map(function(n){return{type:"LineString",coordinates:n}})},n.outline=function(){return{type:"Polygon",coordinates:[h(u).concat(p(c).slice(1),h(i).reverse().slice(1),p(l).reverse().slice(1))]}},n.extent=function(t){return arguments.length?n.majorExtent(t).minorExtent(t):n.minorExtent()},n.majorExtent=function(t){return arguments.length?(u=+t[0][0],i=+t[1][0],l=+t[0][1],c=+t[1][1],u>i&&(t=u,u=i,i=t),l>c&&(t=l,l=c,c=t),n.precision(m)):[[u,l],[i,c]]},n.minorExtent=function(t){return arguments.length?(r=+t[0][0],e=+t[1][0],a=+t[0][1],o=+t[1][1],r>e&&(t=r,r=e,e=t),a>o&&(t=a,a=o,o=t),n.precision(m)):[[r,a],[e,o]]},n.step=function(t){return arguments.length?n.majorStep(t).minorStep(t):n.minorStep()},n.majorStep=function(t){return arguments.length?(d=+t[0],y=+t[1],n):[d,y]},n.minorStep=function(t){return arguments.length?(g=+t[0],v=+t[1],n):[g,v]},n.precision=function(t){return arguments.length?(m=+t,f=te(a,o,90),s=ee(r,e,m),h=te(l,c,90),p=ee(u,i,m),n):m},n.majorExtent([[-180,-90+_u],[180,90-_u]]).minorExtent([[-180,-80-_u],[180,80+_u]])},Ji.geo.greatArc=function(){function n(){return{type:"LineString",coordinates:[t||r.apply(this,arguments),e||i.apply(this,arguments)]}}var t,e,r=re,i=ie;return n.distance=function(){return Ji.geo.distance(t||r.apply(this,arguments),e||i.apply(this,arguments))},n.source=function(e){return arguments.length?(r=e,t="function"==typeof e?null:e,n):r},n.target=function(t){return arguments.length?(i=t,e="function"==typeof t?null:t,n):i},n.precision=function(){return arguments.length?n:0},n},Ji.geo.interpolate=function(n,t){return function(n,t,e,r){var i=Math.cos(t),u=Math.sin(t),o=Math.cos(r),a=Math.sin(r),c=i*Math.cos(n),l=i*Math.sin(n),f=o*Math.cos(e),s=o*Math.sin(e),h=2*Math.asin(Math.sqrt(tn(r-t)+i*o*tn(e-n))),p=1/Math.sin(h),g=h?function(n){var t=Math.sin(n*=h)*p,e=Math.sin(h-n)*p,r=e*c+t*f,i=e*l+t*s,o=e*u+t*a;return[Math.atan2(i,r)*Cu,Math.atan2(o,Math.sqrt(r*r+i*i))*Cu]}:function(){return[n*Cu,t*Cu]};return g.distance=h,g}(n[0]*Au,n[1]*Au,t[0]*Au,t[1]*Au)},Ji.geo.length=function(n){return Po=0,Ji.geo.stream(n,Uo),Po};var Po,Uo={sphere:x,point:x,lineStart:function(){function n(n,i){var u=Math.sin(i*=Au),o=Math.cos(i),a=ou((n*=Au)-t),c=Math.cos(a);Po+=Math.atan2(Math.sqrt((a=o*Math.sin(a))*a+(a=r*u-e*o*c)*a),e*u+r*o*c),t=n,e=u,r=o}var t,e,r;Uo.point=function(i,u){t=i*Au,e=Math.sin(u*=Au),r=Math.cos(u),Uo.point=n},Uo.lineEnd=function(){Uo.point=Uo.lineEnd=x}},lineEnd:x,polygonStart:x,polygonEnd:x},jo=ue(function(n){return Math.sqrt(2/(1+n))},function(n){return 2*Math.asin(n/2)});(Ji.geo.azimuthalEqualArea=function(){return Zt(jo)}).raw=jo;var Fo=ue(function(n){var t=Math.acos(n);return t&&t/Math.sin(t)},y);(Ji.geo.azimuthalEquidistant=function(){return Zt(Fo)}).raw=Fo,(Ji.geo.conicConformal=function(){return qt(oe)}).raw=oe,(Ji.geo.conicEquidistant=function(){return qt(ae)}).raw=ae;var Ho=ue(function(n){return 1/n},Math.atan);(Ji.geo.gnomonic=function(){return Zt(Ho)}).raw=Ho,ce.invert=function(n,t){return[n,2*Math.atan(Math.exp(t))-Eu]},(Ji.geo.mercator=function(){return le(ce)}).raw=ce;var Oo=ue(function(){return 1},Math.asin);(Ji.geo.orthographic=function(){return Zt(Oo)}).raw=Oo;var Io=ue(function(n){return 1/(1+n)},function(n){return 2*Math.atan(n)});(Ji.geo.stereographic=function(){return Zt(Io)}).raw=Io,fe.invert=function(n,t){return[-t,2*Math.atan(Math.exp(n))-Eu]},(Ji.geo.transverseMercator=function(){var n=le(fe),t=n.center,e=n.rotate;return n.center=function(n){return n?t([-n[1],n[0]]):[(n=t())[1],-n[0]]},n.rotate=function(n){return n?e([n[0],n[1],n.length>2?n[2]+90:90]):[(n=e())[0],n[1],n[2]-90]},e([0,0,90])}).raw=fe,Ji.geom={},Ji.geom.hull=function(n){function t(n){if(n.length<3)return[];var t,i=wn(e),u=wn(r),o=n.length,a=[],c=[];for(t=0;o>t;t++)a.push([+i.call(this,n[t],t),+u.call(this,n[t],t),t]);for(a.sort(ge),t=0;o>t;t++)c.push([a[t][0],-a[t][1]]);var l=pe(a),f=pe(c),s=f[0]===l[0],h=f[f.length-1]===l[l.length-1],p=[];for(t=l.length-1;t>=0;--t)p.push(n[a[l[t]][2]]);for(t=+s;t<f.length-h;++t)p.push(n[a[f[t]][2]]);return p}var e=se,r=he;return arguments.length?t(n):(t.x=function(n){return arguments.length?(e=n,t):e},t.y=function(n){return arguments.length?(r=n,t):r},t)},Ji.geom.polygon=function(n){return su(n,Yo),n};var Yo=Ji.geom.polygon.prototype=[];Yo.area=function(){for(var n,t=-1,e=this.length,r=this[e-1],i=0;++t<e;)n=r,r=this[t],i+=n[1]*r[0]-n[0]*r[1];return.5*i},Yo.centroid=function(n){var t,e,r=-1,i=this.length,u=0,o=0,a=this[i-1];for(arguments.length||(n=-1/(6*this.area()));++r<i;)t=a,a=this[r],e=t[0]*a[1]-a[0]*t[1],u+=(t[0]+a[0])*e,o+=(t[1]+a[1])*e;return[u*n,o*n]},Yo.clip=function(n){for(var t,e,r,i,u,o,a=ye(n),c=-1,l=this.length-ye(this),f=this[l-1];++c<l;){for(t=n.slice(),n.length=0,i=this[c],u=t[(r=t.length-a)-1],e=-1;++e<r;)ve(o=t[e],f,i)?(ve(u,f,i)||n.push(de(u,o,f,i)),n.push(o)):ve(u,f,i)&&n.push(de(u,o,f,i)),u=o;a&&n.push(n[0]),f=i}return n};var Zo,Vo,Xo,$o,Bo,Wo=[],Jo=[];ke.prototype.prepare=function(){for(var n,t=this.edges,e=t.length;e--;)(n=t[e].edge).b&&n.a||t.splice(e,1);return t.sort(Ne),t.length},De.prototype={start:function(){return this.edge.l===this.site?this.edge.a:this.edge.b},end:function(){return this.edge.l===this.site?this.edge.b:this.edge.a}},Pe.prototype={insert:function(n,t){var e,r,i;if(n){if(t.P=n,t.N=n.N,n.N&&(n.N.P=t),n.N=t,n.R){for(n=n.R;n.L;)n=n.L;n.L=t}else n.R=t;e=n}else this._?(n=He(this._),t.P=null,t.N=n,n.P=n.L=t,e=n):(t.P=t.N=null,this._=t,e=null);for(t.L=t.R=null,t.U=e,t.C=!0,n=t;e&&e.C;)e===(r=e.U).L?(i=r.R)&&i.C?(e.C=i.C=!1,r.C=!0,n=r):(n===e.R&&(je(this,e),e=(n=e).U),e.C=!1,r.C=!0,Fe(this,r)):(i=r.L)&&i.C?(e.C=i.C=!1,r.C=!0,n=r):(n===e.L&&(Fe(this,e),e=(n=e).U),e.C=!1,r.C=!0,je(this,r)),e=n.U;this._.C=!1},remove:function(n){n.N&&(n.N.P=n.P),n.P&&(n.P.N=n.N),n.N=n.P=null;var t,e,r,i=n.U,u=n.L,o=n.R;if(e=u?o?He(o):u:o,i?i.L===n?i.L=e:i.R=e:this._=e,u&&o?(r=e.C,e.C=n.C,e.L=u,u.U=e,e!==o?(i=e.U,e.U=n.U,n=e.R,i.L=n,e.R=o,o.U=e):(e.U=i,i=e,n=e.R)):(r=n.C,n=e),n&&(n.U=i),!r){if(n&&n.C)return void(n.C=!1);do{if(n===this._)break;if(n===i.L){if((t=i.R).C&&(t.C=!1,i.C=!0,je(this,i),t=i.R),t.L&&t.L.C||t.R&&t.R.C){t.R&&t.R.C||(t.L.C=!1,t.C=!0,Fe(this,t),t=i.R),t.C=i.C,i.C=t.R.C=!1,je(this,i),n=this._;break}}else if((t=i.L).C&&(t.C=!1,i.C=!0,Fe(this,i),t=i.L),t.L&&t.L.C||t.R&&t.R.C){t.L&&t.L.C||(t.R.C=!1,t.C=!0,je(this,t),t=i.L),t.C=i.C,i.C=t.L.C=!1,Fe(this,i),n=this._;break}t.C=!0,n=i,i=i.U}while(!n.C);n&&(n.C=!1)}}},Ji.geom.voronoi=function(n){function t(n){var t=new Array(n.length),r=a[0][0],i=a[0][1],u=a[1][0],o=a[1][1];return Oe(e(n),a).cells.forEach(function(e,a){var c=e.edges,l=e.site;(t[a]=c.length?c.map(function(n){var t=n.start();return[t.x,t.y]}):l.x>=r&&l.x<=u&&l.y>=i&&l.y<=o?[[r,o],[u,o],[u,i],[r,i]]:[]).point=n[a]}),t}function e(n){return n.map(function(n,t){return{x:Math.round(u(n,t)/_u)*_u,y:Math.round(o(n,t)/_u)*_u,i:t}})}var r=se,i=he,u=r,o=i,a=Go;return n?t(n):(t.links=function(n){return Oe(e(n)).edges.filter(function(n){return n.l&&n.r}).map(function(t){return{source:n[t.l.i],target:n[t.r.i]}})},t.triangles=function(n){var t=[];return Oe(e(n)).cells.forEach(function(e,r){for(var i,u=e.site,o=e.edges.sort(Ne),a=-1,c=o.length,l=o[c-1].edge,f=l.l===u?l.r:l.l;++a<c;)l,i=f,f=(l=o[a].edge).l===u?l.r:l.l,r<i.i&&r<f.i&&Ye(u,i,f)<0&&t.push([n[r],n[i.i],n[f.i]])}),t},t.x=function(n){return arguments.length?(u=wn(r=n),t):r},t.y=function(n){return arguments.length?(o=wn(i=n),t):i},t.clipExtent=function(n){return arguments.length?(a=null==n?Go:n,t):a===Go?null:a},t.size=function(n){return arguments.length?t.clipExtent(n&&[[0,0],n]):a===Go?null:a&&a[1]},t)};var Go=[[-1e6,-1e6],[1e6,1e6]];Ji.geom.delaunay=function(n){return Ji.geom.voronoi().triangles(n)},Ji.geom.quadtree=function(n,t,e,r,i){function u(n){function u(n,t,e,r,i,u,o,a){if(!isNaN(e)&&!isNaN(r))if(n.leaf){var c=n.x,f=n.y;if(null!=c)if(ou(c-e)+ou(f-r)<.01)l(n,t,e,r,i,u,o,a);else{var s=n.point;n.x=n.y=n.point=null,l(n,s,c,f,i,u,o,a),l(n,t,e,r,i,u,o,a)}else n.x=e,n.y=r,n.point=t}else l(n,t,e,r,i,u,o,a)}function l(n,t,e,r,i,o,a,c){var l=.5*(i+a),f=.5*(o+c),s=e>=l,h=r>=f,p=h<<1|s;n.leaf=!1,s?i=l:a=l,h?o=f:c=f,u(n=n.nodes[p]||(n.nodes[p]={leaf:!0,nodes:[],point:null,x:null,y:null}),t,e,r,i,o,a,c)}var f,s,h,p,g,v,d,y,m,M=wn(a),x=wn(c);if(null!=t)v=t,d=e,y=r,m=i;else if(y=m=-(v=d=1/0),s=[],h=[],g=n.length,o)for(p=0;g>p;++p)(f=n[p]).x<v&&(v=f.x),f.y<d&&(d=f.y),f.x>y&&(y=f.x),f.y>m&&(m=f.y),s.push(f.x),h.push(f.y);else for(p=0;g>p;++p){var b=+M(f=n[p],p),_=+x(f,p);v>b&&(v=b),d>_&&(d=_),b>y&&(y=b),_>m&&(m=_),s.push(b),h.push(_)}var w=y-v,S=m-d;w>S?m=d+w:y=v+S;var k={leaf:!0,nodes:[],point:null,x:null,y:null,add:function(n){u(k,n,+M(n,++p),+x(n,p),v,d,y,m)}};if(k.visit=function(n){!function n(t,e,r,i,u,o){if(!t(e,r,i,u,o)){var a=.5*(r+u),c=.5*(i+o),l=e.nodes;l[0]&&n(t,l[0],r,i,a,c),l[1]&&n(t,l[1],a,i,u,c),l[2]&&n(t,l[2],r,c,a,o),l[3]&&n(t,l[3],a,c,u,o)}}(n,k,v,d,y,m)},k.find=function(n){return function(n,t,e,r,i,u,o){var a,c=1/0;return function n(l,f,s,h,p){if(!(f>u||s>o||r>h||i>p)){if(g=l.point){var g,v=t-l.x,d=e-l.y,y=v*v+d*d;if(c>y){var m=Math.sqrt(c=y);r=t-m,i=e-m,u=t+m,o=e+m,a=g}}for(var M=l.nodes,x=.5*(f+h),b=.5*(s+p),_=(e>=b)<<1|t>=x,w=_+4;w>_;++_)if(l=M[3&_])switch(3&_){case 0:n(l,f,s,x,b);break;case 1:n(l,x,s,h,b);break;case 2:n(l,f,b,x,p);break;case 3:n(l,x,b,h,p)}}}(n,r,i,u,o),a}(k,n[0],n[1],v,d,y,m)},p=-1,null==t){for(;++p<g;)u(k,n[p],s[p],h[p],v,d,y,m);--p}else n.forEach(k.add);return s=h=n=f=null,k}var o,a=se,c=he;return(o=arguments.length)?(a=Ze,c=Ve,3===o&&(i=e,r=t,e=t=0),u(n)):(u.x=function(n){return arguments.length?(a=n,u):a},u.y=function(n){return arguments.length?(c=n,u):c},u.extent=function(n){return arguments.length?(null==n?t=e=r=i=null:(t=+n[0][0],e=+n[0][1],r=+n[1][0],i=+n[1][1]),u):null==t?null:[[t,e],[r,i]]},u.size=function(n){return arguments.length?(null==n?t=e=r=i=null:(t=e=0,r=+n[0],i=+n[1]),u):null==t?null:[r-t,i-e]},u)},Ji.interpolateRgb=Xe,Ji.interpolateObject=$e,Ji.interpolateNumber=Be,Ji.interpolateString=We;var Ko=/[-+]?(?:\d+\.?\d*|\.?\d+)(?:[eE][-+]?\d+)?/g,Qo=new RegExp(Ko.source,"g");Ji.interpolate=Je,Ji.interpolators=[function(n,t){var e=typeof t;return("string"===e?Yu.has(t.toLowerCase())||/^(#|rgb\(|hsl\()/i.test(t)?Xe:We:t instanceof en?Xe:Array.isArray(t)?Ge:"object"===e&&isNaN(t)?$e:Be)(n,t)}],Ji.interpolateArray=Ge;var na=function(){return y},ta=Ji.map({linear:na,poly:function(n){return function(t){return Math.pow(t,n)}},quad:function(){return nr},cubic:function(){return tr},sin:function(){return rr},exp:function(){return ir},circle:function(){return ur},elastic:function(n,t){var e;return arguments.length<2&&(t=.45),arguments.length?e=t/ku*Math.asin(1/n):(n=1,e=t/4),function(r){return 1+n*Math.pow(2,-10*r)*Math.sin((r-e)*ku/t)}},back:function(n){return n||(n=1.70158),function(t){return t*t*((n+1)*t-n)}},bounce:function(){return or}}),ea=Ji.map({in:y,out:Ke,"in-out":Qe,"out-in":function(n){return Qe(Ke(n))}});Ji.ease=function(n){var t=n.indexOf("-"),e=t>=0?n.slice(0,t):n,r=t>=0?n.slice(t+1):"in";return e=ta.get(e)||na,function(n){return function(t){return 0>=t?0:t>=1?1:n(t)}}((r=ea.get(r)||y)(e.apply(null,Gi.call(arguments,1))))},Ji.interpolateHcl=function(n,t){n=Ji.hcl(n),t=Ji.hcl(t);var e=n.h,r=n.c,i=n.l,u=t.h-e,o=t.c-r,a=t.l-i;return isNaN(o)&&(o=0,r=isNaN(r)?t.c:r),isNaN(u)?(u=0,e=isNaN(e)?t.h:e):u>180?u-=360:-180>u&&(u+=360),function(n){return an(e+u*n,r+o*n,i+a*n)+""}},Ji.interpolateHsl=function(n,t){n=Ji.hsl(n),t=Ji.hsl(t);var e=n.h,r=n.s,i=n.l,u=t.h-e,o=t.s-r,a=t.l-i;return isNaN(o)&&(o=0,r=isNaN(r)?t.s:r),isNaN(u)?(u=0,e=isNaN(e)?t.h:e):u>180?u-=360:-180>u&&(u+=360),function(n){return un(e+u*n,r+o*n,i+a*n)+""}},Ji.interpolateLab=function(n,t){n=Ji.lab(n),t=Ji.lab(t);var e=n.l,r=n.a,i=n.b,u=t.l-e,o=t.a-r,a=t.b-i;return function(n){return ln(e+u*n,r+o*n,i+a*n)+""}},Ji.interpolateRound=ar,Ji.transform=function(n){var t=Qi.createElementNS(Ji.ns.prefix.svg,"g");return(Ji.transform=function(n){if(null!=n){t.setAttribute("transform",n);var e=t.transform.baseVal.consolidate()}return new cr(e?e.matrix:ra)})(n)},cr.prototype.toString=function(){return"translate("+this.translate+")rotate("+this.rotate+")skewX("+this.skew+")scale("+this.scale+")"};var ra={a:1,b:0,c:0,d:1,e:0,f:0};Ji.interpolateTransform=sr,Ji.layout={},Ji.layout.bundle=function(){return function(n){for(var t=[],e=-1,r=n.length;++e<r;)t.push(gr(n[e]));return t}},Ji.layout.chord=function(){function n(){var n,l,s,h,p,g={},v=[],d=Ji.range(u),y=[];for(e=[],r=[],n=0,h=-1;++h<u;){for(l=0,p=-1;++p<u;)l+=i[h][p];v.push(l),y.push(Ji.range(u)),n+=l}for(o&&d.sort(function(n,t){return o(v[n],v[t])}),a&&y.forEach(function(n,t){n.sort(function(n,e){return a(i[t][n],i[t][e])})}),n=(ku-f*u)/n,l=0,h=-1;++h<u;){for(s=l,p=-1;++p<u;){var m=d[h],M=y[m][p],x=i[m][M],b=l,_=l+=x*n;g[m+"-"+M]={index:m,subindex:M,startAngle:b,endAngle:_,value:x}}r[m]={index:m,startAngle:s,endAngle:l,value:(l-s)/n},l+=f}for(h=-1;++h<u;)for(p=h-1;++p<u;){var w=g[h+"-"+p],S=g[p+"-"+h];(w.value||S.value)&&e.push(w.value<S.value?{source:S,target:w}:{source:w,target:S})}c&&t()}function t(){e.sort(function(n,t){return c((n.source.value+n.target.value)/2,(t.source.value+t.target.value)/2)})}var e,r,i,u,o,a,c,l={},f=0;return l.matrix=function(n){return arguments.length?(u=(i=n)&&i.length,e=r=null,l):i},l.padding=function(n){return arguments.length?(f=n,e=r=null,l):f},l.sortGroups=function(n){return arguments.length?(o=n,e=r=null,l):o},l.sortSubgroups=function(n){return arguments.length?(a=n,e=null,l):a},l.sortChords=function(n){return arguments.length?(c=n,e&&t(),l):c},l.chords=function(){return e||n(),e},l.groups=function(){return r||n(),r},l},Ji.layout.force=function(){function n(n){return function(t,e,r,i){if(t.point!==n){var u=t.cx-n.x,o=t.cy-n.y,a=i-e,c=u*u+o*o;if(c>a*a/d){if(g>c){var l=t.charge/c;n.px-=u*l,n.py-=o*l}return!0}if(t.point&&c&&g>c){l=t.pointCharge/c;n.px-=u*l,n.py-=o*l}}return!t.charge}}function t(n){n.px=Ji.event.x,n.py=Ji.event.y,a.resume()}var e,r,i,u,o,a={},c=Ji.dispatch("start","tick","end"),l=[1,1],f=.9,s=ia,h=ua,p=-30,g=oa,v=.1,d=.64,m=[],M=[];return a.tick=function(){if((r*=.99)<.005)return c.end({type:"end",alpha:r=0}),!0;var t,e,a,s,h,g,d,y,x,b=m.length,_=M.length;for(e=0;_>e;++e)s=(a=M[e]).source,(g=(y=(h=a.target).x-s.x)*y+(x=h.y-s.y)*x)&&(y*=g=r*u[e]*((g=Math.sqrt(g))-i[e])/g,x*=g,h.x-=y*(d=s.weight/(h.weight+s.weight)),h.y-=x*d,s.x+=y*(d=1-d),s.y+=x*d);if((d=r*v)&&(y=l[0]/2,x=l[1]/2,e=-1,d))for(;++e<b;)(a=m[e]).x+=(y-a.x)*d,a.y+=(x-a.y)*d;if(p)for(function n(t,e,r){var i=0,u=0;if(t.charge=0,!t.leaf)for(var o,a=t.nodes,c=a.length,l=-1;++l<c;)null!=(o=a[l])&&(n(o,e,r),t.charge+=o.charge,i+=o.charge*o.cx,u+=o.charge*o.cy);if(t.point){t.leaf||(t.point.x+=Math.random()-.5,t.point.y+=Math.random()-.5);var f=e*r[t.point.index];t.charge+=t.pointCharge=f,i+=f*t.point.x,u+=f*t.point.y}t.cx=i/t.charge,t.cy=u/t.charge}(t=Ji.geom.quadtree(m),r,o),e=-1;++e<b;)(a=m[e]).fixed||t.visit(n(a));for(e=-1;++e<b;)(a=m[e]).fixed?(a.x=a.px,a.y=a.py):(a.x-=(a.px-(a.px=a.x))*f,a.y-=(a.py-(a.py=a.y))*f);c.tick({type:"tick",alpha:r})},a.nodes=function(n){return arguments.length?(m=n,a):m},a.links=function(n){return arguments.length?(M=n,a):M},a.size=function(n){return arguments.length?(l=n,a):l},a.linkDistance=function(n){return arguments.length?(s="function"==typeof n?n:+n,a):s},a.distance=a.linkDistance,a.linkStrength=function(n){return arguments.length?(h="function"==typeof n?n:+n,a):h},a.friction=function(n){return arguments.length?(f=+n,a):f},a.charge=function(n){return arguments.length?(p="function"==typeof n?n:+n,a):p},a.chargeDistance=function(n){return arguments.length?(g=n*n,a):Math.sqrt(g)},a.gravity=function(n){return arguments.length?(v=+n,a):v},a.theta=function(n){return arguments.length?(d=n*n,a):Math.sqrt(d)},a.alpha=function(n){return arguments.length?(n=+n,r?r=n>0?n:0:n>0&&(c.start({type:"start",alpha:r=n}),Ji.timer(a.tick)),a):r},a.start=function(){function n(n,r){if(!e){for(e=new Array(c),a=0;c>a;++a)e[a]=[];for(a=0;f>a;++a){var i=M[a];e[i.source.index].push(i.target),e[i.target.index].push(i.source)}}for(var u,o=e[t],a=-1,l=o.length;++a<l;)if(!isNaN(u=o[a][n]))return u;return Math.random()*r}var t,e,r,c=m.length,f=M.length,g=l[0],v=l[1];for(t=0;c>t;++t)(r=m[t]).index=t,r.weight=0;for(t=0;f>t;++t)"number"==typeof(r=M[t]).source&&(r.source=m[r.source]),"number"==typeof r.target&&(r.target=m[r.target]),++r.source.weight,++r.target.weight;for(t=0;c>t;++t)r=m[t],isNaN(r.x)&&(r.x=n("x",g)),isNaN(r.y)&&(r.y=n("y",v)),isNaN(r.px)&&(r.px=r.x),isNaN(r.py)&&(r.py=r.y);if(i=[],"function"==typeof s)for(t=0;f>t;++t)i[t]=+s.call(this,M[t],t);else for(t=0;f>t;++t)i[t]=s;if(u=[],"function"==typeof h)for(t=0;f>t;++t)u[t]=+h.call(this,M[t],t);else for(t=0;f>t;++t)u[t]=h;if(o=[],"function"==typeof p)for(t=0;c>t;++t)o[t]=+p.call(this,m[t],t);else for(t=0;c>t;++t)o[t]=p;return a.resume()},a.resume=function(){return a.alpha(.1)},a.stop=function(){return a.alpha(0)},a.drag=function(){return e||(e=Ji.behavior.drag().origin(y).on("dragstart.force",dr).on("drag.force",t).on("dragend.force",yr)),arguments.length?void this.on("mouseover.force",mr).on("mouseout.force",Mr).call(e):e},Ji.rebind(a,c,"on")};var ia=20,ua=1,oa=1/0;Ji.layout.hierarchy=function(){function n(i){var u,o=[i],a=[];for(i.depth=0;null!=(u=o.pop());)if(a.push(u),(l=e.call(n,u,u.depth))&&(c=l.length)){for(var c,l,f;--c>=0;)o.push(f=l[c]),f.parent=u,f.depth=u.depth+1;r&&(u.value=0),u.children=l}else r&&(u.value=+r.call(n,u,u.depth)||0),delete u.children;return _r(i,function(n){var e,i;t&&(e=n.children)&&e.sort(t),r&&(i=n.parent)&&(i.value+=n.value)}),a}var t=kr,e=wr,r=Sr;return n.sort=function(e){return arguments.length?(t=e,n):t},n.children=function(t){return arguments.length?(e=t,n):e},n.value=function(t){return arguments.length?(r=t,n):r},n.revalue=function(t){return r&&(br(t,function(n){n.children&&(n.value=0)}),_r(t,function(t){var e;t.children||(t.value=+r.call(n,t,t.depth)||0),(e=t.parent)&&(e.value+=t.value)})),t},n},Ji.layout.partition=function(){function n(n,r){var i=t.call(this,n,r);return function n(t,e,r,i){var u=t.children;if(t.x=e,t.y=t.depth*i,t.dx=r,t.dy=i,u&&(o=u.length)){var o,a,c,l=-1;for(r=t.value?r/t.value:0;++l<o;)n(a=u[l],e,c=a.value*r,i),e+=c}}(i[0],0,e[0],e[1]/function n(t){var e=t.children,r=0;if(e&&(i=e.length))for(var i,u=-1;++u<i;)r=Math.max(r,n(e[u]));return 1+r}(i[0])),i}var t=Ji.layout.hierarchy(),e=[1,1];return n.size=function(t){return arguments.length?(e=t,n):e},xr(n,t)},Ji.layout.pie=function(){function n(o){var a,c=o.length,l=o.map(function(e,r){return+t.call(n,e,r)}),f=+("function"==typeof r?r.apply(this,arguments):r),s=("function"==typeof i?i.apply(this,arguments):i)-f,h=Math.min(Math.abs(s)/c,+("function"==typeof u?u.apply(this,arguments):u)),p=h*(0>s?-1:1),g=(s-c*p)/Ji.sum(l),v=Ji.range(c),d=[];return null!=e&&v.sort(e===aa?function(n,t){return l[t]-l[n]}:function(n,t){return e(o[n],o[t])}),v.forEach(function(n){d[n]={data:o[n],value:a=l[n],startAngle:f,endAngle:f+=a*g+p,padAngle:h}}),d}var t=Number,e=aa,r=0,i=ku,u=0;return n.value=function(e){return arguments.length?(t=e,n):t},n.sort=function(t){return arguments.length?(e=t,n):e},n.startAngle=function(t){return arguments.length?(r=t,n):r},n.endAngle=function(t){return arguments.length?(i=t,n):i},n.padAngle=function(t){return arguments.length?(u=t,n):u},n};var aa={};Ji.layout.stack=function(){function n(a,c){if(!(h=a.length))return a;var l=a.map(function(e,r){return t.call(n,e,r)}),f=l.map(function(t){return t.map(function(t,e){return[u.call(n,t,e),o.call(n,t,e)]})}),s=e.call(n,f,c);l=Ji.permute(l,s),f=Ji.permute(f,s);var h,p,g,v,d=r.call(n,f,c),y=l[0].length;for(g=0;y>g;++g)for(i.call(n,l[0][g],v=d[g],f[0][g][1]),p=1;h>p;++p)i.call(n,l[p][g],v+=f[p-1][g][1],f[p][g][1]);return a}var t=y,e=zr,r=qr,i=Cr,u=Er,o=Ar;return n.values=function(e){return arguments.length?(t=e,n):t},n.order=function(t){return arguments.length?(e="function"==typeof t?t:ca.get(t)||zr,n):e},n.offset=function(t){return arguments.length?(r="function"==typeof t?t:la.get(t)||qr,n):r},n.x=function(t){return arguments.length?(u=t,n):u},n.y=function(t){return arguments.length?(o=t,n):o},n.out=function(t){return arguments.length?(i=t,n):i},n};var ca=Ji.map({"inside-out":function(n){var t,e,r=n.length,i=n.map(Lr),u=n.map(Tr),o=Ji.range(r).sort(function(n,t){return i[n]-i[t]}),a=0,c=0,l=[],f=[];for(t=0;r>t;++t)e=o[t],c>a?(a+=u[e],l.push(e)):(c+=u[e],f.push(e));return f.reverse().concat(l)},reverse:function(n){return Ji.range(n.length).reverse()},default:zr}),la=Ji.map({silhouette:function(n){var t,e,r,i=n.length,u=n[0].length,o=[],a=0,c=[];for(e=0;u>e;++e){for(t=0,r=0;i>t;t++)r+=n[t][e][1];r>a&&(a=r),o.push(r)}for(e=0;u>e;++e)c[e]=(a-o[e])/2;return c},wiggle:function(n){var t,e,r,i,u,o,a,c,l,f=n.length,s=n[0],h=s.length,p=[];for(p[0]=c=l=0,e=1;h>e;++e){for(t=0,i=0;f>t;++t)i+=n[t][e][1];for(t=0,u=0,a=s[e][0]-s[e-1][0];f>t;++t){for(r=0,o=(n[t][e][1]-n[t][e-1][1])/(2*a);t>r;++r)o+=(n[r][e][1]-n[r][e-1][1])/a;u+=o*n[t][e][1]}p[e]=c-=i?u/i*a:0,l>c&&(l=c)}for(e=0;h>e;++e)p[e]-=l;return p},expand:function(n){var t,e,r,i=n.length,u=n[0].length,o=1/i,a=[];for(e=0;u>e;++e){for(t=0,r=0;i>t;t++)r+=n[t][e][1];if(r)for(t=0;i>t;t++)n[t][e][1]/=r;else for(t=0;i>t;t++)n[t][e][1]=o}for(e=0;u>e;++e)a[e]=0;return a},zero:qr});Ji.layout.histogram=function(){function n(n,u){for(var o,a,c=[],l=n.map(e,this),f=r.call(this,l,u),s=i.call(this,f,l,u),h=(u=-1,l.length),p=s.length-1,g=t?1:1/h;++u<p;)(o=c[u]=[]).dx=s[u+1]-(o.x=s[u]),o.y=0;if(p>0)for(u=-1;++u<h;)(a=l[u])>=f[0]&&a<=f[1]&&((o=c[Ji.bisect(s,a,1,p)-1]).y+=g,o.push(n[u]));return c}var t=!0,e=Number,r=Ur,i=Dr;return n.value=function(t){return arguments.length?(e=t,n):e},n.range=function(t){return arguments.length?(r=wn(t),n):r},n.bins=function(t){return arguments.length?(i="number"==typeof t?function(n){return Pr(n,t)}:wn(t),n):i},n.frequency=function(e){return arguments.length?(t=!!e,n):t},n},Ji.layout.pack=function(){function n(n,u){var o=e.call(this,n,u),a=o[0],c=i[0],l=i[1],f=null==t?Math.sqrt:"function"==typeof t?t:function(){return t};if(a.x=a.y=0,_r(a,function(n){n.r=+f(n.value)}),_r(a,Ir),r){var s=r*(t?1:Math.max(2*a.r/c,2*a.r/l))/2;_r(a,function(n){n.r+=s}),_r(a,Ir),_r(a,function(n){n.r-=s})}return function n(t,e,r,i){var u=t.children;if(t.x=e+=i*t.x,t.y=r+=i*t.y,t.r*=i,u)for(var o=-1,a=u.length;++o<a;)n(u[o],e,r,i)}(a,c/2,l/2,t?1:1/Math.max(2*a.r/c,2*a.r/l)),o}var t,e=Ji.layout.hierarchy().sort(jr),r=0,i=[1,1];return n.size=function(t){return arguments.length?(i=t,n):i},n.radius=function(e){return arguments.length?(t=null==e||"function"==typeof e?e:+e,n):t},n.padding=function(t){return arguments.length?(r=+t,n):r},xr(n,e)},Ji.layout.tree=function(){function n(n,c){var l=i.call(this,n,c),f=l[0],s=function(n){for(var t,e={A:null,children:[n]},r=[e];null!=(t=r.pop());)for(var i,u=t.children,o=0,a=u.length;a>o;++o)r.push((u[o]=i={_:u[o],parent:t,children:(i=u[o].children)&&i.slice()||[],A:null,a:null,z:0,m:0,c:0,s:0,t:null,i:o}).a=i);return e.children[0]}(f);if(_r(s,t),s.parent.m=-s.z,br(s,e),a)br(f,r);else{var h=f,p=f,g=f;br(f,function(n){n.x<h.x&&(h=n),n.x>p.x&&(p=n),n.depth>g.depth&&(g=n)});var v=u(h,p)/2-h.x,d=o[0]/(p.x+u(p,h)/2+v),y=o[1]/(g.depth||1);br(f,function(n){n.x=(n.x+v)*d,n.y=n.depth*y})}return l}function t(n){var t=n.children,e=n.parent.children,r=n.i?e[n.i-1]:null;if(t.length){!function(n){for(var t,e=0,r=0,i=n.children,u=i.length;--u>=0;)(t=i[u]).z+=e,t.m+=e,e+=t.s+(r+=t.c)}(n);var i=(t[0].z+t[t.length-1].z)/2;r?(n.z=r.z+u(n._,r._),n.m=n.z-i):n.z=i}else r&&(n.z=r.z+u(n._,r._));n.parent.A=function(n,t,e){if(t){for(var r,i=n,o=n,a=t,c=i.parent.children[0],l=i.m,f=o.m,s=a.m,h=c.m;a=Br(a),i=$r(i),a&&i;)c=$r(c),(o=Br(o)).a=n,(r=a.z+s-i.z-l+u(a._,i._))>0&&(Wr(Jr(a,n,e),n,r),l+=r,f+=r),s+=a.m,l+=i.m,h+=c.m,f+=o.m;a&&!Br(o)&&(o.t=a,o.m+=s-f),i&&!$r(c)&&(c.t=i,c.m+=l-h,e=n)}return e}(n,r,n.parent.A||e[0])}function e(n){n._.x=n.z+n.parent.m,n.m+=n.parent.m}function r(n){n.x*=o[0],n.y=n.depth*o[1]}var i=Ji.layout.hierarchy().sort(null).value(null),u=Xr,o=[1,1],a=null;return n.separation=function(t){return arguments.length?(u=t,n):u},n.size=function(t){return arguments.length?(a=null==(o=t)?r:null,n):a?null:o},n.nodeSize=function(t){return arguments.length?(a=null==(o=t)?null:r,n):a?o:null},xr(n,i)},Ji.layout.cluster=function(){function n(n,u){var o,a=t.call(this,n,u),c=a[0],l=0;_r(c,function(n){var t=n.children;t&&t.length?(n.x=function(n){return n.reduce(function(n,t){return n+t.x},0)/n.length}(t),n.y=function(n){return 1+Ji.max(n,function(n){return n.y})}(t)):(n.x=o?l+=e(n,o):0,n.y=0,o=n)});var f=function n(t){var e=t.children;return e&&e.length?n(e[0]):t}(c),s=function n(t){var e,r=t.children;return r&&(e=r.length)?n(r[e-1]):t}(c),h=f.x-e(f,s)/2,p=s.x+e(s,f)/2;return _r(c,i?function(n){n.x=(n.x-c.x)*r[0],n.y=(c.y-n.y)*r[1]}:function(n){n.x=(n.x-h)/(p-h)*r[0],n.y=(1-(c.y?n.y/c.y:1))*r[1]}),a}var t=Ji.layout.hierarchy().sort(null).value(null),e=Xr,r=[1,1],i=!1;return n.separation=function(t){return arguments.length?(e=t,n):e},n.size=function(t){return arguments.length?(i=null==(r=t),n):i?null:r},n.nodeSize=function(t){return arguments.length?(i=null!=(r=t),n):i?r:null},xr(n,t)},Ji.layout.treemap=function(){function n(n,t){for(var e,r,i=-1,u=n.length;++i<u;)r=(e=n[i]).value*(0>t?0:t),e.area=isNaN(r)||0>=r?0:r}function t(e){var u=e.children;if(u&&u.length){var o,a,c,l=s(e),f=[],h=u.slice(),g=1/0,v="slice"===p?l.dx:"dice"===p?l.dy:"slice-dice"===p?1&e.depth?l.dy:l.dx:Math.min(l.dx,l.dy);for(n(h,l.dx*l.dy/e.value),f.area=0;(c=h.length)>0;)f.push(o=h[c-1]),f.area+=o.area,"squarify"!==p||(a=r(f,v))<=g?(h.pop(),g=a):(f.area-=f.pop().area,i(f,v,l,!1),v=Math.min(l.dx,l.dy),f.length=f.area=0,g=1/0);f.length&&(i(f,v,l,!0),f.length=f.area=0),u.forEach(t)}}function e(t){var r=t.children;if(r&&r.length){var u,o=s(t),a=r.slice(),c=[];for(n(a,o.dx*o.dy/t.value),c.area=0;u=a.pop();)c.push(u),c.area+=u.area,null!=u.z&&(i(c,u.z?o.dx:o.dy,o,!a.length),c.length=c.area=0);r.forEach(e)}}function r(n,t){for(var e,r=n.area,i=0,u=1/0,o=-1,a=n.length;++o<a;)(e=n[o].area)&&(u>e&&(u=e),e>i&&(i=e));return t*=t,(r*=r)?Math.max(t*i*g/r,r/(t*u*g)):1/0}function i(n,t,e,r){var i,u=-1,o=n.length,a=e.x,l=e.y,f=t?c(n.area/t):0;if(t==e.dx){for((r||f>e.dy)&&(f=e.dy);++u<o;)(i=n[u]).x=a,i.y=l,i.dy=f,a+=i.dx=Math.min(e.x+e.dx-a,f?c(i.area/f):0);i.z=!0,i.dx+=e.x+e.dx-a,e.y+=f,e.dy-=f}else{for((r||f>e.dx)&&(f=e.dx);++u<o;)(i=n[u]).x=a,i.y=l,i.dx=f,l+=i.dy=Math.min(e.y+e.dy-l,f?c(i.area/f):0);i.z=!1,i.dy+=e.y+e.dy-l,e.x+=f,e.dx-=f}}function u(r){var i=o||a(r),u=i[0];return u.x=0,u.y=0,u.dx=l[0],u.dy=l[1],o&&a.revalue(u),n([u],u.dx*u.dy/u.value),(o?e:t)(u),h&&(o=i),i}var o,a=Ji.layout.hierarchy(),c=Math.round,l=[1,1],f=null,s=Gr,h=!1,p="squarify",g=.5*(1+Math.sqrt(5));return u.size=function(n){return arguments.length?(l=n,u):l},u.padding=function(n){function t(t){return Kr(t,n)}return arguments.length?(s=null==(f=n)?Gr:"function"==(e=typeof n)?function(t){var e=n.call(u,t,t.depth);return null==e?Gr(t):Kr(t,"number"==typeof e?[e,e,e,e]:e)}:"number"===e?(n=[n,n,n,n],t):t,u):f;var e},u.round=function(n){return arguments.length?(c=n?Math.round:Number,u):c!=Number},u.sticky=function(n){return arguments.length?(h=n,o=null,u):h},u.ratio=function(n){return arguments.length?(g=n,u):g},u.mode=function(n){return arguments.length?(p=n+"",u):p},xr(u,a)},Ji.random={normal:function(n,t){var e=arguments.length;return 2>e&&(t=1),1>e&&(n=0),function(){var e,r,i;do{i=(e=2*Math.random()-1)*e+(r=2*Math.random()-1)*r}while(!i||i>1);return n+t*e*Math.sqrt(-2*Math.log(i)/i)}},logNormal:function(){var n=Ji.random.normal.apply(Ji,arguments);return function(){return Math.exp(n())}},bates:function(n){var t=Ji.random.irwinHall(n);return function(){return t()/n}},irwinHall:function(n){return function(){for(var t=0,e=0;n>e;e++)t+=Math.random();return t}}},Ji.scale={};var fa={floor:y,ceil:y};Ji.scale.linear=function(){return function n(t,e,r,i){function u(){var n=Math.min(t.length,e.length)>2?ri:ti,u=i?pr:hr;return a=n(t,e,u,r),c=n(e,t,u,Je),o}function o(n){return a(n)}var a,c;return o.invert=function(n){return c(n)},o.domain=function(n){return arguments.length?(t=n.map(Number),u()):t},o.range=function(n){return arguments.length?(e=n,u()):e},o.rangeRound=function(n){return o.range(n).interpolate(ar)},o.clamp=function(n){return arguments.length?(i=n,u()):i},o.interpolate=function(n){return arguments.length?(r=n,u()):r},o.ticks=function(n){return ai(t,n)},o.tickFormat=function(n,e){return ci(t,n,e)},o.nice=function(n){return ui(t,n),u()},o.copy=function(){return n(t,e,r,i)},u()}([0,1],[0,1],Je,!1)};var sa={s:1,g:1,p:1,r:1,e:1};Ji.scale.log=function(){return function n(t,e,r,i){function u(n){return(r?Math.log(0>n?0:n):-Math.log(n>0?0:-n))/Math.log(e)}function o(n){return r?Math.pow(e,n):-Math.pow(e,-n)}function a(n){return t(u(n))}return a.invert=function(n){return o(t.invert(n))},a.domain=function(n){return arguments.length?(r=n[0]>=0,t.domain((i=n.map(Number)).map(u)),a):i},a.base=function(n){return arguments.length?(e=+n,t.domain(i.map(u)),a):e},a.nice=function(){var n=ei(i.map(u),r?Math:pa);return t.domain(n),i=n.map(o),a},a.ticks=function(){var n=Qr(i),t=[],a=n[0],c=n[1],l=Math.floor(u(a)),f=Math.ceil(u(c)),s=e%1?2:e;if(isFinite(f-l)){if(r){for(;f>l;l++)for(var h=1;s>h;h++)t.push(o(l)*h);t.push(o(l))}else for(t.push(o(l));l++<f;)for(h=s-1;h>0;h--)t.push(o(l)*h);for(l=0;t[l]<a;l++);for(f=t.length;t[f-1]>c;f--);t=t.slice(l,f)}return t},a.tickFormat=function(n,t){if(!arguments.length)return ha;arguments.length<2?t=ha:"function"!=typeof t&&(t=Ji.format(t));var e,i=Math.max(.1,n/a.ticks().length),c=r?(e=1e-12,Math.ceil):(e=-1e-12,Math.floor);return function(n){return n/o(c(u(n)+e))<=i?t(n):""}},a.copy=function(){return n(t.copy(),e,r,i)},ii(a,t)}(Ji.scale.linear().domain([0,1]),10,!0,[1,10])};var ha=Ji.format(".0e"),pa={floor:function(n){return-Math.ceil(-n)},ceil:function(n){return-Math.floor(-n)}};Ji.scale.pow=function(){return function n(t,e,r){function i(n){return t(u(n))}var u=fi(e),o=fi(1/e);return i.invert=function(n){return o(t.invert(n))},i.domain=function(n){return arguments.length?(t.domain((r=n.map(Number)).map(u)),i):r},i.ticks=function(n){return ai(r,n)},i.tickFormat=function(n,t){return ci(r,n,t)},i.nice=function(n){return i.domain(ui(r,n))},i.exponent=function(n){return arguments.length?(u=fi(e=n),o=fi(1/e),t.domain(r.map(u)),i):e},i.copy=function(){return n(t.copy(),e,r)},ii(i,t)}(Ji.scale.linear(),1,[0,1])},Ji.scale.sqrt=function(){return Ji.scale.pow().exponent(.5)},Ji.scale.ordinal=function(){return function n(t,e){function r(n){return o[((u.get(n)||("range"===e.t?u.set(n,t.push(n)):NaN))-1)%o.length]}function i(n,e){return Ji.range(t.length).map(function(t){return n+e*t})}var u,o,a;return r.domain=function(n){if(!arguments.length)return t;t=[],u=new c;for(var i,o=-1,a=n.length;++o<a;)u.has(i=n[o])||u.set(i,t.push(i));return r[e.t].apply(r,e.a)},r.range=function(n){return arguments.length?(o=n,a=0,e={t:"range",a:arguments},r):o},r.rangePoints=function(n,u){arguments.length<2&&(u=0);var c=n[0],l=n[1],f=t.length<2?(c=(c+l)/2,0):(l-c)/(t.length-1+u);return o=i(c+f*u/2,f),a=0,e={t:"rangePoints",a:arguments},r},r.rangeRoundPoints=function(n,u){arguments.length<2&&(u=0);var c=n[0],l=n[1],f=t.length<2?(c=l=Math.round((c+l)/2),0):(l-c)/(t.length-1+u)|0;return o=i(c+Math.round(f*u/2+(l-c-(t.length-1+u)*f)/2),f),a=0,e={t:"rangeRoundPoints",a:arguments},r},r.rangeBands=function(n,u,c){arguments.length<2&&(u=0),arguments.length<3&&(c=u);var l=n[1]<n[0],f=n[l-0],s=(n[1-l]-f)/(t.length-u+2*c);return o=i(f+s*c,s),l&&o.reverse(),a=s*(1-u),e={t:"rangeBands",a:arguments},r},r.rangeRoundBands=function(n,u,c){arguments.length<2&&(u=0),arguments.length<3&&(c=u);var l=n[1]<n[0],f=n[l-0],s=n[1-l],h=Math.floor((s-f)/(t.length-u+2*c));return o=i(f+Math.round((s-f-(t.length-u)*h)/2),h),l&&o.reverse(),a=Math.round(h*(1-u)),e={t:"rangeRoundBands",a:arguments},r},r.rangeBand=function(){return a},r.rangeExtent=function(){return Qr(e.a[0])},r.copy=function(){return n(t,e)},r.domain(t)}([],{t:"range",a:[[]]})},Ji.scale.category10=function(){return Ji.scale.ordinal().range(ga)},Ji.scale.category20=function(){return Ji.scale.ordinal().range(va)},Ji.scale.category20b=function(){return Ji.scale.ordinal().range(da)},Ji.scale.category20c=function(){return Ji.scale.ordinal().range(ya)};var ga=[2062260,16744206,2924588,14034728,9725885,9197131,14907330,8355711,12369186,1556175].map(dn),va=[2062260,11454440,16744206,16759672,2924588,10018698,14034728,16750742,9725885,12955861,9197131,12885140,14907330,16234194,8355711,13092807,12369186,14408589,1556175,10410725].map(dn),da=[3750777,5395619,7040719,10264286,6519097,9216594,11915115,13556636,9202993,12426809,15186514,15190932,8666169,11356490,14049643,15177372,8077683,10834324,13528509,14589654].map(dn),ya=[3244733,7057110,10406625,13032431,15095053,16616764,16625259,16634018,3253076,7652470,10607003,13101504,7695281,10394312,12369372,14342891,6513507,9868950,12434877,14277081].map(dn);Ji.scale.quantile=function(){return function n(t,u){function o(){var n=0,e=u.length;for(c=[];++n<e;)c[n-1]=Ji.quantile(t,n/e);return a}function a(n){return isNaN(n=+n)?void 0:u[Ji.bisect(c,n)]}var c;return a.domain=function(n){return arguments.length?(t=n.map(r).filter(i).sort(e),o()):t},a.range=function(n){return arguments.length?(u=n,o()):u},a.quantiles=function(){return c},a.invertExtent=function(n){return 0>(n=u.indexOf(n))?[NaN,NaN]:[n>0?c[n-1]:t[0],n<c.length?c[n]:t[t.length-1]]},a.copy=function(){return n(t,u)},o()}([],[])},Ji.scale.quantize=function(){return function n(t,e,r){function i(n){return r[Math.max(0,Math.min(a,Math.floor(o*(n-t))))]}function u(){return o=r.length/(e-t),a=r.length-1,i}var o,a;return i.domain=function(n){return arguments.length?(t=+n[0],e=+n[n.length-1],u()):[t,e]},i.range=function(n){return arguments.length?(r=n,u()):r},i.invertExtent=function(n){return[n=0>(n=r.indexOf(n))?NaN:n/o+t,n+1/o]},i.copy=function(){return n(t,e,r)},u()}(0,1,[0,1])},Ji.scale.threshold=function(){return function n(t,e){function r(n){return n>=n?e[Ji.bisect(t,n)]:void 0}return r.domain=function(n){return arguments.length?(t=n,r):t},r.range=function(n){return arguments.length?(e=n,r):e},r.invertExtent=function(n){return n=e.indexOf(n),[t[n-1],t[n]]},r.copy=function(){return n(t,e)},r}([.5],[0,1])},Ji.scale.identity=function(){return function n(t){function e(n){return+n}return e.invert=e,e.domain=e.range=function(n){return arguments.length?(t=n.map(e),e):t},e.ticks=function(n){return ai(t,n)},e.tickFormat=function(n,e){return ci(t,n,e)},e.copy=function(){return n(t)},e}([0,1])},Ji.svg={},Ji.svg.arc=function(){function n(){var n=Math.max(0,+e.apply(this,arguments)),l=Math.max(0,+r.apply(this,arguments)),f=o.apply(this,arguments)-Eu,s=a.apply(this,arguments)-Eu,h=f>s?0:1;if(n>l&&(p=l,l=n,n=p),Math.abs(s-f)>=Nu)return t(l,h)+(n?t(n,1-h):"")+"Z";var p,g,v,d,y,m,M,x,b,_,w,S,k=0,N=0,E=[];if((d=(+c.apply(this,arguments)||0)/2)&&(v=u===ma?Math.sqrt(n*n+l*l):+u.apply(this,arguments),h||(N*=-1),l&&(N=Q(v/l*Math.sin(d))),n&&(k=Q(v/n*Math.sin(d)))),l){y=l*Math.cos(f+N),m=l*Math.sin(f+N),M=l*Math.cos(s-N),x=l*Math.sin(s-N);var A=Math.abs(s-f-2*N)<=Su?0:1;if(N&&yi(y,m,M,x)===h^A){var C=(f+s)/2;y=l*Math.cos(C),m=l*Math.sin(C),M=x=null}}else y=m=0;if(n){b=n*Math.cos(s-k),_=n*Math.sin(s-k),w=n*Math.cos(f+k),S=n*Math.sin(f+k);var z=Math.abs(f-s+2*k)<=Su?0:1;if(k&&yi(b,_,w,S)===1-h^z){var q=(f+s)/2;b=n*Math.cos(q),_=n*Math.sin(q),w=S=null}}else b=_=0;if((p=Math.min(Math.abs(l-n)/2,+i.apply(this,arguments)))>.001){g=l>n^h?0:1;var L=null==w?[b,_]:null==M?[y,m]:de([y,m],[w,S],[M,x],[b,_]),T=y-L[0],R=m-L[1],D=M-L[0],P=x-L[1],U=1/Math.sin(Math.acos((T*D+R*P)/(Math.sqrt(T*T+R*R)*Math.sqrt(D*D+P*P)))/2),j=Math.sqrt(L[0]*L[0]+L[1]*L[1]);if(null!=M){var F=Math.min(p,(l-j)/(U+1)),H=mi(null==w?[b,_]:[w,S],[y,m],l,F,h),O=mi([M,x],[b,_],l,F,h);p===F?E.push("M",H[0],"A",F,",",F," 0 0,",g," ",H[1],"A",l,",",l," 0 ",1-h^yi(H[1][0],H[1][1],O[1][0],O[1][1]),",",h," ",O[1],"A",F,",",F," 0 0,",g," ",O[0]):E.push("M",H[0],"A",F,",",F," 0 1,",g," ",O[0])}else E.push("M",y,",",m);if(null!=w){var I=Math.min(p,(n-j)/(U-1)),Y=mi([y,m],[w,S],n,-I,h),Z=mi([b,_],null==M?[y,m]:[M,x],n,-I,h);p===I?E.push("L",Z[0],"A",I,",",I," 0 0,",g," ",Z[1],"A",n,",",n," 0 ",h^yi(Z[1][0],Z[1][1],Y[1][0],Y[1][1]),",",1-h," ",Y[1],"A",I,",",I," 0 0,",g," ",Y[0]):E.push("L",Z[0],"A",I,",",I," 0 0,",g," ",Y[0])}else E.push("L",b,",",_)}else E.push("M",y,",",m),null!=M&&E.push("A",l,",",l," 0 ",A,",",h," ",M,",",x),E.push("L",b,",",_),null!=w&&E.push("A",n,",",n," 0 ",z,",",1-h," ",w,",",S);return E.push("Z"),E.join("")}function t(n,t){return"M0,"+n+"A"+n+","+n+" 0 1,"+t+" 0,"+-n+"A"+n+","+n+" 0 1,"+t+" 0,"+n}var e=hi,r=pi,i=si,u=ma,o=gi,a=vi,c=di;return n.innerRadius=function(t){return arguments.length?(e=wn(t),n):e},n.outerRadius=function(t){return arguments.length?(r=wn(t),n):r},n.cornerRadius=function(t){return arguments.length?(i=wn(t),n):i},n.padRadius=function(t){return arguments.length?(u=t==ma?ma:wn(t),n):u},n.startAngle=function(t){return arguments.length?(o=wn(t),n):o},n.endAngle=function(t){return arguments.length?(a=wn(t),n):a},n.padAngle=function(t){return arguments.length?(c=wn(t),n):c},n.centroid=function(){var n=(+e.apply(this,arguments)+ +r.apply(this,arguments))/2,t=(+o.apply(this,arguments)+ +a.apply(this,arguments))/2-Eu;return[Math.cos(t)*n,Math.sin(t)*n]},n};var ma="auto";Ji.svg.line=function(){return Mi(y)};var Ma=Ji.map({linear:xi,"linear-closed":function(n){return xi(n)+"Z"},step:function(n){for(var t=0,e=n.length,r=n[0],i=[r[0],",",r[1]];++t<e;)i.push("H",(r[0]+(r=n[t])[0])/2,"V",r[1]);return e>1&&i.push("H",r[0]),i.join("")},"step-before":bi,"step-after":_i,basis:ki,"basis-open":function(n){if(n.length<4)return xi(n);for(var t,e=[],r=-1,i=n.length,u=[0],o=[0];++r<3;)t=n[r],u.push(t[0]),o.push(t[1]);for(e.push(Ni(_a,u)+","+Ni(_a,o)),--r;++r<i;)t=n[r],u.shift(),u.push(t[0]),o.shift(),o.push(t[1]),Ei(e,u,o);return e.join("")},"basis-closed":function(n){for(var t,e,r=-1,i=n.length,u=i+4,o=[],a=[];++r<4;)e=n[r%i],o.push(e[0]),a.push(e[1]);for(t=[Ni(_a,o),",",Ni(_a,a)],--r;++r<u;)e=n[r%i],o.shift(),o.push(e[0]),a.shift(),a.push(e[1]),Ei(t,o,a);return t.join("")},bundle:function(n,t){var e=n.length-1;if(e)for(var r,i,u=n[0][0],o=n[0][1],a=n[e][0]-u,c=n[e][1]-o,l=-1;++l<=e;)i=l/e,(r=n[l])[0]=t*r[0]+(1-t)*(u+i*a),r[1]=t*r[1]+(1-t)*(o+i*c);return ki(n)},cardinal:function(n,t){return n.length<3?xi(n):n[0]+wi(n,Si(n,t))},"cardinal-open":function(n,t){return n.length<4?xi(n):n[1]+wi(n.slice(1,-1),Si(n,t))},"cardinal-closed":function(n,t){return n.length<3?xi(n):n[0]+wi((n.push(n[0]),n),Si([n[n.length-2]].concat(n,[n[1]]),t))},monotone:function(n){return n.length<3?xi(n):n[0]+wi(n,Ci(n))}});Ma.forEach(function(n,t){t.key=n,t.closed=/-closed$/.test(n)});var xa=[0,2/3,1/3,0],ba=[0,1/3,2/3,0],_a=[0,1/6,2/3,1/6];Ji.svg.line.radial=function(){var n=Mi(zi);return n.radius=n.x,delete n.x,n.angle=n.y,delete n.y,n},bi.reverse=_i,_i.reverse=bi,Ji.svg.area=function(){return qi(y)},Ji.svg.area.radial=function(){var n=qi(zi);return n.radius=n.x,delete n.x,n.innerRadius=n.x0,delete n.x0,n.outerRadius=n.x1,delete n.x1,n.angle=n.y,delete n.y,n.startAngle=n.y0,delete n.y0,n.endAngle=n.y1,delete n.y1,n},Ji.svg.chord=function(){function n(n,o){var a=t(this,i,n,o),c=t(this,u,n,o);return"M"+a.p0+e(a.r,a.p1,a.a1-a.a0)+(function(n,t){return n.a0==t.a0&&n.a1==t.a1}(a,c)?r(a.r,a.p1,a.r,a.p0):r(a.r,a.p1,c.r,c.p0)+e(c.r,c.p1,c.a1-c.a0)+r(c.r,c.p1,a.r,a.p0))+"Z"}function t(n,t,e,r){var i=t.call(n,e,r),u=o.call(n,i,r),l=a.call(n,i,r)-Eu,f=c.call(n,i,r)-Eu;return{r:u,a0:l,a1:f,p0:[u*Math.cos(l),u*Math.sin(l)],p1:[u*Math.cos(f),u*Math.sin(f)]}}function e(n,t,e){return"A"+n+","+n+" 0 "+ +(e>Su)+",1 "+t}function r(n,t,e,r){return"Q 0,0 "+r}var i=re,u=ie,o=Li,a=gi,c=vi;return n.radius=function(t){return arguments.length?(o=wn(t),n):o},n.source=function(t){return arguments.length?(i=wn(t),n):i},n.target=function(t){return arguments.length?(u=wn(t),n):u},n.startAngle=function(t){return arguments.length?(a=wn(t),n):a},n.endAngle=function(t){return arguments.length?(c=wn(t),n):c},n},Ji.svg.diagonal=function(){function n(n,i){var u=t.call(this,n,i),o=e.call(this,n,i),a=(u.y+o.y)/2,c=[u,{x:u.x,y:a},{x:o.x,y:a},o];return"M"+(c=c.map(r))[0]+"C"+c[1]+" "+c[2]+" "+c[3]}var t=re,e=ie,r=Ti;return n.source=function(e){return arguments.length?(t=wn(e),n):t},n.target=function(t){return arguments.length?(e=wn(t),n):e},n.projection=function(t){return arguments.length?(r=t,n):r},n},Ji.svg.diagonal.radial=function(){var n=Ji.svg.diagonal(),t=Ti,e=n.projection;return n.projection=function(n){return arguments.length?e(function(n){return function(){var t=n.apply(this,arguments),e=t[0],r=t[1]-Eu;return[e*Math.cos(r),e*Math.sin(r)]}}(t=n)):t},n},Ji.svg.symbol=function(){function n(n,r){return(wa.get(t.call(this,n,r))||Pi)(e.call(this,n,r))}var t=Di,e=Ri;return n.type=function(e){return arguments.length?(t=wn(e),n):t},n.size=function(t){return arguments.length?(e=wn(t),n):e},n};var wa=Ji.map({circle:Pi,cross:function(n){var t=Math.sqrt(n/5)/2;return"M"+-3*t+","+-t+"H"+-t+"V"+-3*t+"H"+t+"V"+-t+"H"+3*t+"V"+t+"H"+t+"V"+3*t+"H"+-t+"V"+t+"H"+-3*t+"Z"},diamond:function(n){var t=Math.sqrt(n/(2*ka)),e=t*ka;return"M0,"+-t+"L"+e+",0 0,"+t+" "+-e+",0Z"},square:function(n){var t=Math.sqrt(n)/2;return"M"+-t+","+-t+"L"+t+","+-t+" "+t+","+t+" "+-t+","+t+"Z"},"triangle-down":function(n){var t=Math.sqrt(n/Sa),e=t*Sa/2;return"M0,"+e+"L"+t+","+-e+" "+-t+","+-e+"Z"},"triangle-up":function(n){var t=Math.sqrt(n/Sa),e=t*Sa/2;return"M0,"+-e+"L"+t+","+e+" "+-t+","+e+"Z"}});Ji.svg.symbolTypes=wa.keys();var Sa=Math.sqrt(3),ka=Math.tan(30*Au);vu.transition=function(n){for(var t,e,r=Na||++za,i=Oi(n),u=[],o=Ea||{time:Date.now(),ease:er,delay:0,duration:250},a=-1,c=this.length;++a<c;){u.push(t=[]);for(var l=this[a],f=-1,s=l.length;++f<s;)(e=l[f])&&Ii(e,f,i,r,o),t.push(e)}return ji(u,i,r)},vu.interrupt=function(n){return this.each(null==n?Aa:Ui(Oi(n)))};var Na,Ea,Aa=Ui(Oi()),Ca=[],za=0;Ca.call=vu.call,Ca.empty=vu.empty,Ca.node=vu.node,Ca.size=vu.size,Ji.transition=function(n,t){return n&&n.transition?Na?n.transition(t):n:Ji.selection().transition(n)},Ji.transition.prototype=Ca,Ca.select=function(n){var t,e,r,i=this.id,u=this.namespace,o=[];n=E(n);for(var a=-1,c=this.length;++a<c;){o.push(t=[]);for(var l=this[a],f=-1,s=l.length;++f<s;)(r=l[f])&&(e=n.call(r,r.__data__,f,a))?("__data__"in r&&(e.__data__=r.__data__),Ii(e,f,u,i,r[u][i]),t.push(e)):t.push(null)}return ji(o,u,i)},Ca.selectAll=function(n){var t,e,r,i,u,o=this.id,a=this.namespace,c=[];n=A(n);for(var l=-1,f=this.length;++l<f;)for(var s=this[l],h=-1,p=s.length;++h<p;)if(r=s[h]){u=r[a][o],e=n.call(r,r.__data__,h,l),c.push(t=[]);for(var g=-1,v=e.length;++g<v;)(i=e[g])&&Ii(i,g,a,o,u),t.push(i)}return ji(c,a,o)},Ca.filter=function(n){var t,e,r=[];"function"!=typeof n&&(n=H(n));for(var i=0,u=this.length;u>i;i++){r.push(t=[]);for(var o,a=0,c=(o=this[i]).length;c>a;a++)(e=o[a])&&n.call(e,e.__data__,a,i)&&t.push(e)}return ji(r,this.namespace,this.id)},Ca.tween=function(n,t){var e=this.id,r=this.namespace;return arguments.length<2?this.node()[r][e].tween.get(n):I(this,null==t?function(t){t[r][e].tween.remove(n)}:function(i){i[r][e].tween.set(n,t)})},Ca.attr=function(n,t){function e(){this.removeAttribute(u)}function r(){this.removeAttributeNS(u.space,u.local)}if(arguments.length<2){for(t in n)this.attr(t,n[t]);return this}var i="transform"==n?sr:Je,u=Ji.ns.qualify(n);return Fi(this,"attr."+n,t,u.local?function(n){return null==n?r:(n+="",function(){var t,e=this.getAttributeNS(u.space,u.local);return e!==n&&(t=i(e,n),function(n){this.setAttributeNS(u.space,u.local,t(n))})})}:function(n){return null==n?e:(n+="",function(){var t,e=this.getAttribute(u);return e!==n&&(t=i(e,n),function(n){this.setAttribute(u,t(n))})})})},Ca.attrTween=function(n,t){var e=Ji.ns.qualify(n);return this.tween("attr."+n,e.local?function(n,r){var i=t.call(this,n,r,this.getAttributeNS(e.space,e.local));return i&&function(n){this.setAttributeNS(e.space,e.local,i(n))}}:function(n,r){var i=t.call(this,n,r,this.getAttribute(e));return i&&function(n){this.setAttribute(e,i(n))}})},Ca.style=function(n,e,r){function i(){this.style.removeProperty(n)}var u=arguments.length;if(3>u){if("string"!=typeof n){for(r in 2>u&&(e=""),n)this.style(r,n[r],e);return this}r=""}return Fi(this,"style."+n,e,function(e){return null==e?i:(e+="",function(){var i,u=t(this).getComputedStyle(this,null).getPropertyValue(n);return u!==e&&(i=Je(u,e),function(t){this.style.setProperty(n,i(t),r)})})})},Ca.styleTween=function(n,e,r){return arguments.length<3&&(r=""),this.tween("style."+n,function(i,u){var o=e.call(this,i,u,t(this).getComputedStyle(this,null).getPropertyValue(n));return o&&function(t){this.style.setProperty(n,o(t),r)}})},Ca.text=function(n){return Fi(this,"text",n,Hi)},Ca.remove=function(){var n=this.namespace;return this.each("end.transition",function(){var t;this[n].count<2&&(t=this.parentNode)&&t.removeChild(this)})},Ca.ease=function(n){var t=this.id,e=this.namespace;return arguments.length<1?this.node()[e][t].ease:("function"!=typeof n&&(n=Ji.ease.apply(Ji,arguments)),I(this,function(r){r[e][t].ease=n}))},Ca.delay=function(n){var t=this.id,e=this.namespace;return arguments.length<1?this.node()[e][t].delay:I(this,"function"==typeof n?function(r,i,u){r[e][t].delay=+n.call(r,r.__data__,i,u)}:(n=+n,function(r){r[e][t].delay=n}))},Ca.duration=function(n){var t=this.id,e=this.namespace;return arguments.length<1?this.node()[e][t].duration:I(this,"function"==typeof n?function(r,i,u){r[e][t].duration=Math.max(1,n.call(r,r.__data__,i,u))}:(n=Math.max(1,n),function(r){r[e][t].duration=n}))},Ca.each=function(n,t){var e=this.id,r=this.namespace;if(arguments.length<2){var i=Ea,u=Na;try{Na=e,I(this,function(t,i,u){Ea=t[r][e],n.call(t,t.__data__,i,u)})}finally{Ea=i,Na=u}}else I(this,function(i){var u=i[r][e];(u.event||(u.event=Ji.dispatch("start","end","interrupt"))).on(n,t)});return this},Ca.transition=function(){for(var n,t,e,r=this.id,i=++za,u=this.namespace,o=[],a=0,c=this.length;c>a;a++){o.push(n=[]);for(var l,f=0,s=(l=this[a]).length;s>f;f++)(t=l[f])&&Ii(t,f,u,i,{time:(e=t[u][r]).time,ease:e.ease,delay:e.delay+e.duration,duration:e.duration}),n.push(t)}return ji(o,u,i)},Ji.svg.axis=function(){function n(n){n.each(function(){var n,l=Ji.select(this),f=this.__chart__||e,s=this.__chart__=e.copy(),h=null==c?s.ticks?s.ticks.apply(s,a):s.domain():c,p=null==t?s.tickFormat?s.tickFormat.apply(s,a):y:t,g=l.selectAll(".tick").data(h,s),v=g.enter().insert("g",".domain").attr("class","tick").style("opacity",_u),d=Ji.transition(g.exit()).style("opacity",_u).remove(),m=Ji.transition(g.order()).style("opacity",1),M=Math.max(i,0)+o,x=ni(s),b=l.selectAll(".domain").data([0]),_=(b.enter().append("path").attr("class","domain"),Ji.transition(b));v.append("line"),v.append("text");var w,S,k,N,E=v.select("line"),A=m.select("line"),C=g.select("text").text(p),z=v.select("text"),q=m.select("text"),L="top"===r||"left"===r?-1:1;if("bottom"===r||"top"===r?(n=Yi,w="x",k="y",S="x2",N="y2",C.attr("dy",0>L?"0em":".71em").style("text-anchor","middle"),_.attr("d","M"+x[0]+","+L*u+"V0H"+x[1]+"V"+L*u)):(n=Zi,w="y",k="x",S="y2",N="x2",C.attr("dy",".32em").style("text-anchor",0>L?"end":"start"),_.attr("d","M"+L*u+","+x[0]+"H0V"+x[1]+"H"+L*u)),E.attr(N,L*i),z.attr(k,L*M),A.attr(S,0).attr(N,L*i),q.attr(w,0).attr(k,L*M),s.rangeBand){var T=s,R=T.rangeBand()/2;f=s=function(n){return T(n)+R}}else f.rangeBand?f=s:d.call(n,s,f);v.call(n,f,s),m.call(n,s,s)})}var t,e=Ji.scale.linear(),r=qa,i=6,u=6,o=3,a=[10],c=null;return n.scale=function(t){return arguments.length?(e=t,n):e},n.orient=function(t){return arguments.length?(r=t in La?t+"":qa,n):r},n.ticks=function(){return arguments.length?(a=arguments,n):a},n.tickValues=function(t){return arguments.length?(c=t,n):c},n.tickFormat=function(e){return arguments.length?(t=e,n):t},n.tickSize=function(t){var e=arguments.length;return e?(i=+t,u=+arguments[e-1],n):i},n.innerTickSize=function(t){return arguments.length?(i=+t,n):i},n.outerTickSize=function(t){return arguments.length?(u=+t,n):u},n.tickPadding=function(t){return arguments.length?(o=+t,n):o},n.tickSubdivide=function(){return arguments.length&&n},n};var qa="bottom",La={top:1,right:1,bottom:1,left:1};Ji.svg.brush=function(){function n(t){t.each(function(){var t=Ji.select(this).style("pointer-events","all").style("-webkit-tap-highlight-color","rgba(0,0,0,0)").on("mousedown.brush",u).on("touchstart.brush",u),o=t.selectAll(".background").data([0]);o.enter().append("rect").attr("class","background").style("visibility","hidden").style("cursor","crosshair"),t.selectAll(".extent").data([0]).enter().append("rect").attr("class","extent").style("cursor","move");var a=t.selectAll(".resize").data(v,y);a.exit().remove(),a.enter().append("g").attr("class",function(n){return"resize "+n}).style("cursor",function(n){return Ta[n]}).append("rect").attr("x",function(n){return/[ew]$/.test(n)?-3:null}).attr("y",function(n){return/^[ns]/.test(n)?-3:null}).attr("width",6).attr("height",6).style("visibility","hidden"),a.style("display",n.empty()?"none":null);var c,s=Ji.transition(t),h=Ji.transition(o);l&&(c=ni(l),h.attr("x",c[0]).attr("width",c[1]-c[0]),r(s)),f&&(c=ni(f),h.attr("y",c[0]).attr("height",c[1]-c[0]),i(s)),e(s)})}function e(n){n.selectAll(".resize").attr("transform",function(n){return"translate("+s[+/e$/.test(n)]+","+h[+/^s/.test(n)]+")"})}function r(n){n.select(".extent").attr("x",s[0]),n.selectAll(".extent,.n>rect,.s>rect").attr("width",s[1]-s[0])}function i(n){n.select(".extent").attr("y",h[0]),n.selectAll(".extent,.e>rect,.w>rect").attr("height",h[1]-h[0])}function u(){function u(){var n=Ji.mouse(M),t=!1;m&&(n[0]+=m[0],n[1]+=m[1]),E||(Ji.event.altKey?(y||(y=[(s[0]+s[1])/2,(h[0]+h[1])/2]),C[0]=s[+(n[0]<y[0])],C[1]=h[+(n[1]<y[1])]):y=null),k&&v(n,l,0)&&(r(_),t=!0),N&&v(n,f,1)&&(i(_),t=!0),t&&(e(_),b({type:"brush",mode:E?"move":"resize"}))}function v(n,t,e){var r,i,u=ni(t),c=u[0],l=u[1],f=C[e],v=e?h:s,d=v[1]-v[0];return E&&(c-=f,l-=d+f),r=(e?g:p)?Math.max(c,Math.min(l,n[e])):n[e],E?i=(r+=f)+d:(y&&(f=Math.max(c,Math.min(l,2*y[e]-r))),r>f?(i=r,r=f):i=f),v[0]!=r||v[1]!=i?(e?a=null:o=null,v[0]=r,v[1]=i,!0):void 0}function d(){u(),_.style("pointer-events","all").selectAll(".resize").style("display",n.empty()?"none":null),Ji.select("body").style("cursor",null),z.on("mousemove.brush",null).on("mouseup.brush",null).on("touchmove.brush",null).on("touchend.brush",null).on("keydown.brush",null).on("keyup.brush",null),A(),b({type:"brushend"})}var y,m,M=this,x=Ji.select(Ji.event.target),b=c.of(M,arguments),_=Ji.select(M),S=x.datum(),k=!/^(n|s)$/.test(S)&&l,N=!/^(e|w)$/.test(S)&&f,E=x.classed("extent"),A=$(M),C=Ji.mouse(M),z=Ji.select(t(M)).on("keydown.brush",function(){32==Ji.event.keyCode&&(E||(y=null,C[0]-=s[1],C[1]-=h[1],E=2),w())}).on("keyup.brush",function(){32==Ji.event.keyCode&&2==E&&(C[0]+=s[1],C[1]+=h[1],E=0,w())});if(Ji.event.changedTouches?z.on("touchmove.brush",u).on("touchend.brush",d):z.on("mousemove.brush",u).on("mouseup.brush",d),_.interrupt().selectAll("*").interrupt(),E)C[0]=s[0]-C[0],C[1]=h[0]-C[1];else if(S){var q=+/w$/.test(S),L=+/^n/.test(S);m=[s[1-q]-C[0],h[1-L]-C[1]],C[0]=s[q],C[1]=h[L]}else Ji.event.altKey&&(y=C.slice());_.style("pointer-events","none").selectAll(".resize").style("display",null),Ji.select("body").style("cursor",x.style("cursor")),b({type:"brushstart"}),u()}var o,a,c=k(n,"brushstart","brush","brushend"),l=null,f=null,s=[0,0],h=[0,0],p=!0,g=!0,v=Ra[0];return n.event=function(n){n.each(function(){var n=c.of(this,arguments),t={x:s,y:h,i:o,j:a},e=this.__chart__||t;this.__chart__=t,Na?Ji.select(this).transition().each("start.brush",function(){o=e.i,a=e.j,s=e.x,h=e.y,n({type:"brushstart"})}).tween("brush:brush",function(){var e=Ge(s,t.x),r=Ge(h,t.y);return o=a=null,function(i){s=t.x=e(i),h=t.y=r(i),n({type:"brush",mode:"resize"})}}).each("end.brush",function(){o=t.i,a=t.j,n({type:"brush",mode:"resize"}),n({type:"brushend"})}):(n({type:"brushstart"}),n({type:"brush",mode:"resize"}),n({type:"brushend"}))})},n.x=function(t){return arguments.length?(v=Ra[!(l=t)<<1|!f],n):l},n.y=function(t){return arguments.length?(v=Ra[!l<<1|!(f=t)],n):f},n.clamp=function(t){return arguments.length?(l&&f?(p=!!t[0],g=!!t[1]):l?p=!!t:f&&(g=!!t),n):l&&f?[p,g]:l?p:f?g:null},n.extent=function(t){var e,r,i,u,c;return arguments.length?(l&&(e=t[0],r=t[1],f&&(e=e[0],r=r[0]),o=[e,r],l.invert&&(e=l(e),r=l(r)),e>r&&(c=e,e=r,r=c),(e!=s[0]||r!=s[1])&&(s=[e,r])),f&&(i=t[0],u=t[1],l&&(i=i[1],u=u[1]),a=[i,u],f.invert&&(i=f(i),u=f(u)),i>u&&(c=i,i=u,u=c),(i!=h[0]||u!=h[1])&&(h=[i,u])),n):(l&&(o?(e=o[0],r=o[1]):(e=s[0],r=s[1],l.invert&&(e=l.invert(e),r=l.invert(r)),e>r&&(c=e,e=r,r=c))),f&&(a?(i=a[0],u=a[1]):(i=h[0],u=h[1],f.invert&&(i=f.invert(i),u=f.invert(u)),i>u&&(c=i,i=u,u=c))),l&&f?[[e,i],[r,u]]:l?[e,r]:f&&[i,u])},n.clear=function(){return n.empty()||(s=[0,0],h=[0,0],o=a=null),n},n.empty=function(){return!!l&&s[0]==s[1]||!!f&&h[0]==h[1]},Ji.rebind(n,c,"on")};var Ta={n:"ns-resize",e:"ew-resize",s:"ns-resize",w:"ew-resize",nw:"nwse-resize",ne:"nesw-resize",se:"nwse-resize",sw:"nesw-resize"},Ra=[["n","e","s","w","nw","ne","se","sw"],["e","w"],["n","s"],[]],Da=Qu.format=uo.timeFormat,Pa=Da.utc,Ua=Pa("%Y-%m-%dT%H:%M:%S.%LZ");Da.iso=Date.prototype.toISOString&&+new Date("2000-01-01T00:00:00.000Z")?Vi:Ua,Vi.parse=function(n){var t=new Date(n);return isNaN(t)?null:t},Vi.toString=Ua.toString,Qu.second=Tn(function(n){return new no(1e3*Math.floor(n/1e3))},function(n,t){n.setTime(n.getTime()+1e3*Math.floor(t))},function(n){return n.getSeconds()}),Qu.seconds=Qu.second.range,Qu.seconds.utc=Qu.second.utc.range,Qu.minute=Tn(function(n){return new no(6e4*Math.floor(n/6e4))},function(n,t){n.setTime(n.getTime()+6e4*Math.floor(t))},function(n){return n.getMinutes()}),Qu.minutes=Qu.minute.range,Qu.minutes.utc=Qu.minute.utc.range,Qu.hour=Tn(function(n){var t=n.getTimezoneOffset()/60;return new no(36e5*(Math.floor(n/36e5-t)+t))},function(n,t){n.setTime(n.getTime()+36e5*Math.floor(t))},function(n){return n.getHours()}),Qu.hours=Qu.hour.range,Qu.hours.utc=Qu.hour.utc.range,Qu.month=Tn(function(n){return(n=Qu.day(n)).setDate(1),n},function(n,t){n.setMonth(n.getMonth()+t)},function(n){return n.getMonth()}),Qu.months=Qu.month.range,Qu.months.utc=Qu.month.utc.range;var ja=[1e3,5e3,15e3,3e4,6e4,3e5,9e5,18e5,36e5,108e5,216e5,432e5,864e5,1728e5,6048e5,2592e6,7776e6,31536e6],Fa=[[Qu.second,1],[Qu.second,5],[Qu.second,15],[Qu.second,30],[Qu.minute,1],[Qu.minute,5],[Qu.minute,15],[Qu.minute,30],[Qu.hour,1],[Qu.hour,3],[Qu.hour,6],[Qu.hour,12],[Qu.day,1],[Qu.day,2],[Qu.week,1],[Qu.month,1],[Qu.month,3],[Qu.year,1]],Ha=Da.multi([[".%L",function(n){return n.getMilliseconds()}],[":%S",function(n){return n.getSeconds()}],["%I:%M",function(n){return n.getMinutes()}],["%I %p",function(n){return n.getHours()}],["%a %d",function(n){return n.getDay()&&1!=n.getDate()}],["%b %d",function(n){return 1!=n.getDate()}],["%B",function(n){return n.getMonth()}],["%Y",bt]]),Oa={range:function(n,t,e){return Ji.range(Math.ceil(n/e)*e,+t,e).map($i)},floor:y,ceil:y};Fa.year=Qu.year,Qu.scale=function(){return Xi(Ji.scale.linear(),Fa,Ha)};var Ia=Fa.map(function(n){return[n[0].utc,n[1]]}),Ya=Pa.multi([[".%L",function(n){return n.getUTCMilliseconds()}],[":%S",function(n){return n.getUTCSeconds()}],["%I:%M",function(n){return n.getUTCMinutes()}],["%I %p",function(n){return n.getUTCHours()}],["%a %d",function(n){return n.getUTCDay()&&1!=n.getUTCDate()}],["%b %d",function(n){return 1!=n.getUTCDate()}],["%B",function(n){return n.getUTCMonth()}],["%Y",bt]]);Ia.year=Qu.year.utc,Qu.scale.utc=function(){return Xi(Ji.scale.linear(),Ia,Ya)},Ji.text=Sn(function(n){return n.responseText}),Ji.json=function(n,t){return kn(n,"application/json",Bi,t)},Ji.html=function(n,t){return kn(n,"text/html",Wi,t)},Ji.xml=Sn(function(n){return n.responseXML}),"function"==typeof define&&define.amd?define(Ji):"object"==typeof module&&module.exports&&(module.exports=Ji),this.d3=Ji}();</script><script>window.addEventListener("resize",function(t){}),document.addEventListener("DOMContentLoaded",function(t){var e=100,n=100,r=d3.select("body").append("svg");r.attr("font-family","fontplaceholder");var a=d3.layout.force().gravity(.05).distance(100).charge(-100);var l=[],o=[],i=0,c=10;e=window.innerWidth,n=window.innerHeight,r.attr("width",e).attr("height",n),a.size([e,n]);var s=dataplaceholder;o=[],(l=[]).push({name:s[0].source,cls:"mid",flag:1});for(var d=1;d<s.length;d++){l.push({name:s[d].target,cls:"low",flag:1});var u=1-s[d].value;(i&&i>u||!i)&&(i=u),o.push({source:0,target:d,value:u,key:s[d].target})}!function(t,e){d3.selectAll(".link").remove(),d3.selectAll(".node").remove(),d3.selectAll("circle").remove(),a.nodes(e).links(t).linkDistance(function(t){var e=100*t.value,n=Math.log(e);return e*(isFinite(n)?n:1)+c}).start();var n=r.selectAll(".link").data(t).enter().append("line").attr("stroke","#aaa").style("stroke-width",function(t){return Math.sqrt(t.val)}),l=r.selectAll(".node").data(e),o=l.enter().append("g").attr("class",function(t){return"node "+t.cls}).call(a.drag);o.append("circle").attr("fill",function(t){return"mid"===t.cls?"#F4B400":"#DB4437"}).attr("r",c).on("click",function(t){}),o.append("text").attr("dx",12).attr("dy",".35em").text(function(t){return t.name}).attr("stroke","#333").style("cursor","default").style("pointer-events","none"),l.exit().remove(),a.on("tick",function(){n.attr("x1",function(t){return t.source.x}).attr("y1",function(t){return t.source.y}).attr("x2",function(t){return t.target.x}).attr("y2",function(t){return t.target.y}),o.attr("transform",function(t){return"translate("+t.x+","+t.y+")"})})}(o,l)});</script></head><body></body></html>
        """    
        word = ""
        if isinstance(words, list):
            word = words[0]
        elif isinstance(words, str):
            word = words
        else:
            raise ValueError('wrong type')
        if not word:
            raise ValueError('empty string')
        mostsim = self.similar_by_word(word, depth)
        arr  = [{"source": word, "target": word, "value":1}]
        for item in mostsim: arr.append({"source": word, "target": item[0], "value":item[1]})        
        return html.replace("wordplaceholder", word).replace("fontplaceholder", font).replace("dataplaceholder", str(arr)).replace("\n", "")
        

    @deprecated(
        "Method will be removed in 4.0.0, use "
        "gensim.models.keyedvectors.WordEmbeddingSimilarityIndex instead")
    def similarity_matrix(self, dictionary, tfidf=None, threshold=0.0, exponent=2.0, nonzero_limit=100, dtype=REAL):
        """Construct a term similarity matrix for computing Soft Cosine Measure.

        This creates a sparse term similarity matrix in the :class:`scipy.sparse.csc_matrix` format for computing
        Soft Cosine Measure between documents.

        Parameters
        ----------
        dictionary : :class:`~gensim.corpora.dictionary.Dictionary`
            A dictionary that specifies the considered terms.
        tfidf : :class:`gensim.models.tfidfmodel.TfidfModel` or None, optional
            A model that specifies the relative importance of the terms in the dictionary. The
            columns of the term similarity matrix will be build in a decreasing order of importance
            of terms, or in the order of term identifiers if None.
        threshold : float, optional
            Only embeddings more similar than `threshold` are considered when retrieving word
            embeddings closest to a given word embedding.
        exponent : float, optional
            Take the word embedding similarities larger than `threshold` to the power of `exponent`.
        nonzero_limit : int, optional
            The maximum number of non-zero elements outside the diagonal in a single column of the
            sparse term similarity matrix.
        dtype : numpy.dtype, optional
            Data-type of the sparse term similarity matrix.

        Returns
        -------
        :class:`scipy.sparse.csc_matrix`
            Term similarity matrix.

        See Also
        --------
        :func:`gensim.matutils.softcossim`
            The Soft Cosine Measure.
        :class:`~gensim.similarities.docsim.SoftCosineSimilarity`
            A class for performing corpus-based similarity queries with Soft Cosine Measure.

        Notes
        -----
        The constructed matrix corresponds to the matrix Mrel defined in section 2.1 of
        `Delphine Charlet and Geraldine Damnati, "SimBow at SemEval-2017 Task 3: Soft-Cosine Semantic Similarity
        between Questions for Community Question Answering", 2017
        <http://www.aclweb.org/anthology/S/S17/S17-2051.pdf>`_.

        """
        index = WordEmbeddingSimilarityIndex(self, threshold=threshold, exponent=exponent)
        similarity_matrix = SparseTermSimilarityMatrix(
            index, dictionary, tfidf=tfidf, nonzero_limit=nonzero_limit, dtype=dtype)
        return similarity_matrix.matrix

    def wmdistance(self, document1, document2):
        """Compute the Word Mover's Distance between two documents.

        When using this code, please consider citing the following papers:

        * `Ofir Pele and Michael Werman "A linear time histogram metric for improved SIFT matching"
          <http://www.cs.huji.ac.il/~werman/Papers/ECCV2008.pdf>`_
        * `Ofir Pele and Michael Werman "Fast and robust earth mover's distances"
          <https://ieeexplore.ieee.org/document/5459199/>`_
        * `Matt Kusner et al. "From Word Embeddings To Document Distances"
          <http://proceedings.mlr.press/v37/kusnerb15.pdf>`_.

        Parameters
        ----------
        document1 : list of str
            Input document.
        document2 : list of str
            Input document.

        Returns
        -------
        float
            Word Mover's distance between `document1` and `document2`.

        Warnings
        --------
        This method only works if `pyemd <https://pypi.org/project/pyemd/>`_ is installed.

        If one of the documents have no words that exist in the vocab, `float('inf')` (i.e. infinity)
        will be returned.

        Raises
        ------
        ImportError
            If `pyemd <https://pypi.org/project/pyemd/>`_  isn't installed.

        """

        # If pyemd C extension is available, import it.
        # If pyemd is attempted to be used, but isn't installed, ImportError will be raised in wmdistance
        from pyemd import emd

        # Remove out-of-vocabulary words.
        len_pre_oov1 = len(document1)
        len_pre_oov2 = len(document2)
        document1 = [token for token in document1 if token in self]
        document2 = [token for token in document2 if token in self]
        diff1 = len_pre_oov1 - len(document1)
        diff2 = len_pre_oov2 - len(document2)
        if diff1 > 0 or diff2 > 0:
            logger.info('Removed %d and %d OOV words from document 1 and 2 (respectively).', diff1, diff2)

        if not document1 or not document2:
            logger.info(
                "At least one of the documents had no words that were in the vocabulary. "
                "Aborting (returning inf)."
            )
            return float('inf')

        dictionary = Dictionary(documents=[document1, document2])
        vocab_len = len(dictionary)

        if vocab_len == 1:
            # Both documents are composed by a single unique token
            return 0.0

        # Sets for faster look-up.
        docset1 = set(document1)
        docset2 = set(document2)

        # Compute distance matrix.
        distance_matrix = zeros((vocab_len, vocab_len), dtype=double)
        for i, t1 in dictionary.items():
            if t1 not in docset1:
                continue

            for j, t2 in dictionary.items():
                if t2 not in docset2 or distance_matrix[i, j] != 0.0:
                    continue

                # Compute Euclidean distance between word vectors.
                distance_matrix[i, j] = distance_matrix[j, i] = sqrt(np_sum((self[t1] - self[t2])**2))

        if np_sum(distance_matrix) == 0.0:
            # `emd` gets stuck if the distance matrix contains only zeros.
            logger.info('The distance matrix is all zeros. Aborting (returning inf).')
            return float('inf')

        def nbow(document):
            d = zeros(vocab_len, dtype=double)
            nbow = dictionary.doc2bow(document)  # Word frequencies.
            doc_len = len(document)
            for idx, freq in nbow:
                d[idx] = freq / float(doc_len)  # Normalized word frequencies.
            return d

        # Compute nBOW representation of documents.
        d1 = nbow(document1)
        d2 = nbow(document2)

        # Compute WMD.
        return emd(d1, d2, distance_matrix)

    def most_similar_cosmul(self, positive=None, negative=None, topn=10):
        """Find the top-N most similar words, using the multiplicative combination objective,
        proposed by `Omer Levy and Yoav Goldberg "Linguistic Regularities in Sparse and Explicit Word Representations"
        <http://www.aclweb.org/anthology/W14-1618>`_. Positive words still contribute positively towards the similarity,
        negative words negatively, but with less susceptibility to one large distance dominating the calculation.
        In the common analogy-solving case, of two positive and one negative examples,
        this method is equivalent to the "3CosMul" objective (equation (4)) of Levy and Goldberg.

        Additional positive or negative examples contribute to the numerator or denominator,
        respectively - a potentially sensible but untested extension of the method.
        With a single positive example, rankings will be the same as in the default
        :meth:`~gensim.models.keyedvectors.WordEmbeddingsKeyedVectors.most_similar`.

        Parameters
        ----------
        positive : list of str, optional
            List of words that contribute positively.
        negative : list of str, optional
            List of words that contribute negatively.
        topn : int, optional
            Number of top-N similar words to return.

        Returns
        -------
        list of (str, float)
            Sequence of (word, similarity).

        """
        if positive is None:
            positive = []
        if negative is None:
            negative = []

        self.init_sims()

        if isinstance(positive, string_types) and not negative:
            # allow calls like most_similar_cosmul('dog'), as a shorthand for most_similar_cosmul(['dog'])
            positive = [positive]

        all_words = {
            self.vocab[word].index for word in positive + negative
            if not isinstance(word, ndarray) and word in self.vocab
            }

        positive = [
            self.word_vec(word, use_norm=True) if isinstance(word, string_types) else word
            for word in positive
        ]
        negative = [
            self.word_vec(word, use_norm=True) if isinstance(word, string_types) else word
            for word in negative
        ]

        if not positive:
            raise ValueError("cannot compute similarity with no input")

        # equation (4) of Levy & Goldberg "Linguistic Regularities...",
        # with distances shifted to [0,1] per footnote (7)
        pos_dists = [((1 + dot(self.vectors_norm, term)) / 2) for term in positive]
        neg_dists = [((1 + dot(self.vectors_norm, term)) / 2) for term in negative]
        dists = prod(pos_dists, axis=0) / (prod(neg_dists, axis=0) + 0.000001)

        if not topn:
            return dists
        best = matutils.argsort(dists, topn=topn + len(all_words), reverse=True)
        # ignore (don't return) words from the input
        result = [(self.index2word[sim], float(dists[sim])) for sim in best if sim not in all_words]
        return result[:topn]

    def doesnt_match(self, words):
        """Which word from the given list doesn't go with the others?

        Parameters
        ----------
        words : list of str
            List of words.

        Returns
        -------
        str
            The word further away from the mean of all words.

        """
        self.init_sims()

        used_words = [word for word in words if word in self]
        if len(used_words) != len(words):
            ignored_words = set(words) - set(used_words)
            logger.warning("vectors for words %s are not present in the model, ignoring these words", ignored_words)
        if not used_words:
            raise ValueError("cannot select a word from an empty list")
        vectors = vstack(self.word_vec(word, use_norm=True) for word in used_words).astype(REAL)
        mean = matutils.unitvec(vectors.mean(axis=0)).astype(REAL)
        dists = dot(vectors, mean)
        return sorted(zip(dists, used_words))[0][1]

    @staticmethod
    def cosine_similarities(vector_1, vectors_all):
        """Compute cosine similarities between one vector and a set of other vectors.

        Parameters
        ----------
        vector_1 : numpy.ndarray
            Vector from which similarities are to be computed, expected shape (dim,).
        vectors_all : numpy.ndarray
            For each row in vectors_all, distance from vector_1 is computed, expected shape (num_vectors, dim).

        Returns
        -------
        numpy.ndarray
            Contains cosine distance between `vector_1` and each row in `vectors_all`, shape (num_vectors,).

        """
        norm = np.linalg.norm(vector_1)
        all_norms = np.linalg.norm(vectors_all, axis=1)
        dot_products = dot(vectors_all, vector_1)
        similarities = dot_products / (norm * all_norms)
        return similarities

    def distances(self, word_or_vector, other_words=()):
        """Compute cosine distances from given word or vector to all words in `other_words`.
        If `other_words` is empty, return distance between `word_or_vectors` and all words in vocab.

        Parameters
        ----------
        word_or_vector : {str, numpy.ndarray}
            Word or vector from which distances are to be computed.
        other_words : iterable of str
            For each word in `other_words` distance from `word_or_vector` is computed.
            If None or empty, distance of `word_or_vector` from all words in vocab is computed (including itself).

        Returns
        -------
        numpy.array
            Array containing distances to all words in `other_words` from input `word_or_vector`.

        Raises
        -----
        KeyError
            If either `word_or_vector` or any word in `other_words` is absent from vocab.

        """
        if isinstance(word_or_vector, string_types):
            input_vector = self.word_vec(word_or_vector)
        else:
            input_vector = word_or_vector
        if not other_words:
            other_vectors = self.vectors
        else:
            other_indices = [self.vocab[word].index for word in other_words]
            other_vectors = self.vectors[other_indices]
        return 1 - self.cosine_similarities(input_vector, other_vectors)

    def distance(self, w1, w2):
        """Compute cosine distance between two words.
        Calculate 1 - :meth:`~gensim.models.keyedvectors.WordEmbeddingsKeyedVectors.similarity`.

        Parameters
        ----------
        w1 : str
            Input word.
        w2 : str
            Input word.

        Returns
        -------
        float
            Distance between `w1` and `w2`.

        """
        return 1 - self.similarity(w1, w2)

    def similarity(self, w1, w2):
        """Compute cosine similarity between two words.

        Parameters
        ----------
        w1 : str
            Input word.
        w2 : str
            Input word.

        Returns
        -------
        float
            Cosine similarity between `w1` and `w2`.

        """
        return dot(matutils.unitvec(self[w1]), matutils.unitvec(self[w2]))

    def n_similarity(self, ws1, ws2):
        """Compute cosine similarity between two sets of words.

        Parameters
        ----------
        ws1 : list of str
            Sequence of words.
        ws2: list of str
            Sequence of words.

        Returns
        -------
        numpy.ndarray
            Similarities between `ws1` and `ws2`.

        """
        if not(len(ws1) and len(ws2)):
            raise ZeroDivisionError('At least one of the passed list is empty.')
        v1 = [self[word] for word in ws1]
        v2 = [self[word] for word in ws2]
        return dot(matutils.unitvec(array(v1).mean(axis=0)), matutils.unitvec(array(v2).mean(axis=0)))

    @staticmethod
    def _log_evaluate_word_analogies(section):
        """Calculate score by section, helper for
        :meth:`~gensim.models.keyedvectors.WordEmbeddingsKeyedVectors.evaluate_word_analogies`.

        Parameters
        ----------
        section : dict of (str, (str, str, str, str))
            Section given from evaluation.

        Returns
        -------
        float
            Accuracy score.

        """
        correct, incorrect = len(section['correct']), len(section['incorrect'])
        if correct + incorrect > 0:
            score = correct / (correct + incorrect)
            logger.info("%s: %.1f%% (%i/%i)", section['section'], 100.0 * score, correct, correct + incorrect)
            return score

    def evaluate_word_analogies(self, analogies, restrict_vocab=300000, case_insensitive=True, dummy4unknown=False):
        """Compute performance of the model on an analogy test set.

        This is modern variant of :meth:`~gensim.models.keyedvectors.WordEmbeddingsKeyedVectors.accuracy`, see
        `discussion on GitHub #1935 <https://github.com/RaRe-Technologies/gensim/pull/1935>`_.

        The accuracy is reported (printed to log and returned as a score) for each section separately,
        plus there's one aggregate summary at the end.

        This method corresponds to the `compute-accuracy` script of the original C word2vec.
        See also `Analogy (State of the art) <https://aclweb.org/aclwiki/Analogy_(State_of_the_art)>`_.

        Parameters
        ----------
        analogies : str
            Path to file, where lines are 4-tuples of words, split into sections by ": SECTION NAME" lines.
            See `gensim/test/test_data/questions-words.txt` as example.
        restrict_vocab : int, optional
            Ignore all 4-tuples containing a word not in the first `restrict_vocab` words.
            This may be meaningful if you've sorted the model vocabulary by descending frequency (which is standard
            in modern word embedding models).
        case_insensitive : bool, optional
            If True - convert all words to their uppercase form before evaluating the performance.
            Useful to handle case-mismatch between training tokens and words in the test set.
            In case of multiple case variants of a single word, the vector for the first occurrence
            (also the most frequent if vocabulary is sorted) is taken.
        dummy4unknown : bool, optional
            If True - produce zero accuracies for 4-tuples with out-of-vocabulary words.
            Otherwise, these tuples are skipped entirely and not used in the evaluation.

        Returns
        -------
        score : float
            The overall evaluation score on the entire evaluation set
        sections : list of dict of {str : str or list of tuple of (str, str, str, str)}
            Results broken down by each section of the evaluation set. Each dict contains the name of the section
            under the key 'section', and lists of correctly and incorrectly predicted 4-tuples of words under the
            keys 'correct' and 'incorrect'.

        """
        ok_vocab = [(w, self.vocab[w]) for w in self.index2word[:restrict_vocab]]
        ok_vocab = {w.upper(): v for w, v in reversed(ok_vocab)} if case_insensitive else dict(ok_vocab)
        oov = 0
        logger.info("Evaluating word analogies for top %i words in the model on %s", restrict_vocab, analogies)
        sections, section = [], None
        quadruplets_no = 0
        for line_no, line in enumerate(utils.smart_open(analogies)):
            line = utils.to_unicode(line)
            if line.startswith(': '):
                # a new section starts => store the old section
                if section:
                    sections.append(section)
                    self._log_evaluate_word_analogies(section)
                section = {'section': line.lstrip(': ').strip(), 'correct': [], 'incorrect': []}
            else:
                if not section:
                    raise ValueError("Missing section header before line #%i in %s" % (line_no, analogies))
                try:
                    if case_insensitive:
                        a, b, c, expected = [word.upper() for word in line.split()]
                    else:
                        a, b, c, expected = [word for word in line.split()]
                except ValueError:
                    logger.info("Skipping invalid line #%i in %s", line_no, analogies)
                    continue
                quadruplets_no += 1
                if a not in ok_vocab or b not in ok_vocab or c not in ok_vocab or expected not in ok_vocab:
                    oov += 1
                    if dummy4unknown:
                        logger.debug('Zero accuracy for line #%d with OOV words: %s', line_no, line.strip())
                        section['incorrect'].append((a, b, c, expected))
                    else:
                        logger.debug("Skipping line #%i with OOV words: %s", line_no, line.strip())
                    continue
                original_vocab = self.vocab
                self.vocab = ok_vocab
                ignore = {a, b, c}  # input words to be ignored
                predicted = None
                # find the most likely prediction using 3CosAdd (vector offset) method
                # TODO: implement 3CosMul and set-based methods for solving analogies
                sims = self.most_similar(positive=[b, c], negative=[a], topn=5, restrict_vocab=restrict_vocab)
                self.vocab = original_vocab
                for element in sims:
                    predicted = element[0].upper() if case_insensitive else element[0]
                    if predicted in ok_vocab and predicted not in ignore:
                        if predicted != expected:
                            logger.debug("%s: expected %s, predicted %s", line.strip(), expected, predicted)
                        break
                if predicted == expected:
                    section['correct'].append((a, b, c, expected))
                else:
                    section['incorrect'].append((a, b, c, expected))
        if section:
            # store the last section, too
            sections.append(section)
            self._log_evaluate_word_analogies(section)

        total = {
            'section': 'Total accuracy',
            'correct': list(chain.from_iterable(s['correct'] for s in sections)),
            'incorrect': list(chain.from_iterable(s['incorrect'] for s in sections)),
        }

        oov_ratio = float(oov) / quadruplets_no * 100
        logger.info('Quadruplets with out-of-vocabulary words: %.1f%%', oov_ratio)
        if not dummy4unknown:
            logger.info(
                'NB: analogies containing OOV words were skipped from evaluation! '
                'To change this behavior, use "dummy4unknown=True"'
            )
        analogies_score = self._log_evaluate_word_analogies(total)
        sections.append(total)
        # Return the overall score and the full lists of correct and incorrect analogies
        return analogies_score, sections

    @staticmethod
    def log_accuracy(section):
        correct, incorrect = len(section['correct']), len(section['incorrect'])
        if correct + incorrect > 0:
            logger.info(
                "%s: %.1f%% (%i/%i)",
                section['section'], 100.0 * correct / (correct + incorrect), correct, correct + incorrect
            )

    @deprecated("Method will be removed in 4.0.0, use self.evaluate_word_analogies() instead")
    def accuracy(self, questions, restrict_vocab=30000, most_similar=most_similar, case_insensitive=True):
        """Compute accuracy of the model.

        The accuracy is reported (=printed to log and returned as a list) for each
        section separately, plus there's one aggregate summary at the end.

        Parameters
        ----------
        questions : str
            Path to file, where lines are 4-tuples of words, split into sections by ": SECTION NAME" lines.
            See `gensim/test/test_data/questions-words.txt` as example.
        restrict_vocab : int, optional
            Ignore all 4-tuples containing a word not in the first `restrict_vocab` words.
            This may be meaningful if you've sorted the model vocabulary by descending frequency (which is standard
            in modern word embedding models).
        most_similar : function, optional
            Function used for similarity calculation.
        case_insensitive : bool, optional
            If True - convert all words to their uppercase form before evaluating the performance.
            Useful to handle case-mismatch between training tokens and words in the test set.
            In case of multiple case variants of a single word, the vector for the first occurrence
            (also the most frequent if vocabulary is sorted) is taken.

        Returns
        -------
        list of dict of (str, (str, str, str)
            Full lists of correct and incorrect predictions divided by sections.

        """
        ok_vocab = [(w, self.vocab[w]) for w in self.index2word[:restrict_vocab]]
        ok_vocab = {w.upper(): v for w, v in reversed(ok_vocab)} if case_insensitive else dict(ok_vocab)

        sections, section = [], None
        for line_no, line in enumerate(utils.smart_open(questions)):
            # TODO: use level3 BLAS (=evaluate multiple questions at once), for speed
            line = utils.to_unicode(line)
            if line.startswith(': '):
                # a new section starts => store the old section
                if section:
                    sections.append(section)
                    self.log_accuracy(section)
                section = {'section': line.lstrip(': ').strip(), 'correct': [], 'incorrect': []}
            else:
                if not section:
                    raise ValueError("Missing section header before line #%i in %s" % (line_no, questions))
                try:
                    if case_insensitive:
                        a, b, c, expected = [word.upper() for word in line.split()]
                    else:
                        a, b, c, expected = [word for word in line.split()]
                except ValueError:
                    logger.info("Skipping invalid line #%i in %s", line_no, questions)
                    continue
                if a not in ok_vocab or b not in ok_vocab or c not in ok_vocab or expected not in ok_vocab:
                    logger.debug("Skipping line #%i with OOV words: %s", line_no, line.strip())
                    continue
                original_vocab = self.vocab
                self.vocab = ok_vocab
                ignore = {a, b, c}  # input words to be ignored
                predicted = None
                # find the most likely prediction, ignoring OOV words and input words
                sims = most_similar(self, positive=[b, c], negative=[a], topn=False, restrict_vocab=restrict_vocab)
                self.vocab = original_vocab
                for index in matutils.argsort(sims, reverse=True):
                    predicted = self.index2word[index].upper() if case_insensitive else self.index2word[index]
                    if predicted in ok_vocab and predicted not in ignore:
                        if predicted != expected:
                            logger.debug("%s: expected %s, predicted %s", line.strip(), expected, predicted)
                        break
                if predicted == expected:
                    section['correct'].append((a, b, c, expected))
                else:
                    section['incorrect'].append((a, b, c, expected))
        if section:
            # store the last section, too
            sections.append(section)
            self.log_accuracy(section)

        total = {
            'section': 'total',
            'correct': list(chain.from_iterable(s['correct'] for s in sections)),
            'incorrect': list(chain.from_iterable(s['incorrect'] for s in sections)),
        }
        self.log_accuracy(total)
        sections.append(total)
        return sections

    @staticmethod
    def log_evaluate_word_pairs(pearson, spearman, oov, pairs):
        logger.info('Pearson correlation coefficient against %s: %.4f', pairs, pearson[0])
        logger.info('Spearman rank-order correlation coefficient against %s: %.4f', pairs, spearman[0])
        logger.info('Pairs with unknown words ratio: %.1f%%', oov)

    def evaluate_word_pairs(self, pairs, delimiter='\t', restrict_vocab=300000,
                            case_insensitive=True, dummy4unknown=False):
        """Compute correlation of the model with human similarity judgments.

        Notes
        -----
        More datasets can be found at
        * http://technion.ac.il/~ira.leviant/MultilingualVSMdata.html
        * https://www.cl.cam.ac.uk/~fh295/simlex.html.

        Parameters
        ----------
        pairs : str
            Path to file, where lines are 3-tuples, each consisting of a word pair and a similarity value.
            See `test/test_data/wordsim353.tsv` as example.
        delimiter : str, optional
            Separator in `pairs` file.
        restrict_vocab : int, optional
            Ignore all 4-tuples containing a word not in the first `restrict_vocab` words.
            This may be meaningful if you've sorted the model vocabulary by descending frequency (which is standard
            in modern word embedding models).
        case_insensitive : bool, optional
            If True - convert all words to their uppercase form before evaluating the performance.
            Useful to handle case-mismatch between training tokens and words in the test set.
            In case of multiple case variants of a single word, the vector for the first occurrence
            (also the most frequent if vocabulary is sorted) is taken.
        dummy4unknown : bool, optional
            If True - produce zero accuracies for 4-tuples with out-of-vocabulary words.
            Otherwise, these tuples are skipped entirely and not used in the evaluation.

        Returns
        -------
        pearson : tuple of (float, float)
            Pearson correlation coefficient with 2-tailed p-value.
        spearman : tuple of (float, float)
            Spearman rank-order correlation coefficient between the similarities from the dataset and the
            similarities produced by the model itself, with 2-tailed p-value.
        oov_ratio : float
            The ratio of pairs with unknown words.

        """
        ok_vocab = [(w, self.vocab[w]) for w in self.index2word[:restrict_vocab]]
        ok_vocab = {w.upper(): v for w, v in reversed(ok_vocab)} if case_insensitive else dict(ok_vocab)

        similarity_gold = []
        similarity_model = []
        oov = 0

        original_vocab = self.vocab
        self.vocab = ok_vocab

        for line_no, line in enumerate(utils.smart_open(pairs)):
            line = utils.to_unicode(line)
            if line.startswith('#'):
                # May be a comment
                continue
            else:
                try:
                    if case_insensitive:
                        a, b, sim = [word.upper() for word in line.split(delimiter)]
                    else:
                        a, b, sim = [word for word in line.split(delimiter)]
                    sim = float(sim)
                except (ValueError, TypeError):
                    logger.info('Skipping invalid line #%d in %s', line_no, pairs)
                    continue
                if a not in ok_vocab or b not in ok_vocab:
                    oov += 1
                    if dummy4unknown:
                        logger.debug('Zero similarity for line #%d with OOV words: %s', line_no, line.strip())
                        similarity_model.append(0.0)
                        similarity_gold.append(sim)
                        continue
                    else:
                        logger.debug('Skipping line #%d with OOV words: %s', line_no, line.strip())
                        continue
                similarity_gold.append(sim)  # Similarity from the dataset
                similarity_model.append(self.similarity(a, b))  # Similarity from the model
        self.vocab = original_vocab
        spearman = stats.spearmanr(similarity_gold, similarity_model)
        pearson = stats.pearsonr(similarity_gold, similarity_model)
        if dummy4unknown:
            oov_ratio = float(oov) / len(similarity_gold) * 100
        else:
            oov_ratio = float(oov) / (len(similarity_gold) + oov) * 100

        logger.debug('Pearson correlation coefficient against %s: %f with p-value %f', pairs, pearson[0], pearson[1])
        logger.debug(
            'Spearman rank-order correlation coefficient against %s: %f with p-value %f',
            pairs, spearman[0], spearman[1]
        )
        logger.debug('Pairs with unknown words: %d', oov)
        self.log_evaluate_word_pairs(pearson, spearman, oov_ratio, pairs)
        return pearson, spearman, oov_ratio

    def init_sims(self, replace=False):
        """Precompute L2-normalized vectors.

        Parameters
        ----------
        replace : bool, optional
            If True - forget the original vectors and only keep the normalized ones = saves lots of memory!

        Warnings
        --------
        You **cannot continue training** after doing a replace.
        The model becomes effectively read-only: you can call
        :meth:`~gensim.models.keyedvectors.WordEmbeddingsKeyedVectors.most_similar`,
        :meth:`~gensim.models.keyedvectors.WordEmbeddingsKeyedVectors.similarity`, etc., but not train.

        """
        if getattr(self, 'vectors_norm', None) is None or replace:
            logger.info("precomputing L2-norms of word weight vectors")
            self.vectors_norm = _l2_norm(self.vectors, replace=replace)

    def relative_cosine_similarity(self, wa, wb, topn=10):
        """Compute the relative cosine similarity between two words given top-n similar words,
        by `Artuur Leeuwenberga, Mihaela Velab , Jon Dehdaribc, Josef van Genabithbc "A Minimally Supervised Approach
        for Synonym Extraction with Word Embeddings" <https://ufal.mff.cuni.cz/pbml/105/art-leeuwenberg-et-al.pdf>`_.

        To calculate relative cosine similarity between two words, equation (1) of the paper is used.
        For WordNet synonyms, if rcs(topn=10) is greater than 0.10 then wa and wb are more similar than
        any arbitrary word pairs.

        Parameters
        ----------
        wa: str
            Word for which we have to look top-n similar word.
        wb: str
            Word for which we evaluating relative cosine similarity with wa.
        topn: int, optional
            Number of top-n similar words to look with respect to wa.

        Returns
        -------
        numpy.float64
            Relative cosine similarity between wa and wb.

        """
        sims = self.similar_by_word(wa, topn)
        assert sims, "Failed code invariant: list of similar words must never be empty."
        rcs = float(self.similarity(wa, wb)) / (sum(sim for _, sim in sims))

        return rcs


class WordEmbeddingSimilarityIndex(TermSimilarityIndex):
    """
    Computes cosine similarities between word embeddings and retrieves the closest word embeddings
    by cosine similarity for a given word embedding.

    Parameters
    ----------
    keyedvectors : :class:`~gensim.models.keyedvectors.WordEmbeddingsKeyedVectors`
        The word embeddings.
    threshold : float, optional
        Only embeddings more similar than `threshold` are considered when retrieving word embeddings
        closest to a given word embedding.
    exponent : float, optional
        Take the word embedding similarities larger than `threshold` to the power of `exponent`.
    kwargs : dict or None
        A dict with keyword arguments that will be passed to the `keyedvectors.most_similar` method
        when retrieving the word embeddings closest to a given word embedding.

    See Also
    --------
    :class:`~gensim.similarities.termsim.SparseTermSimilarityMatrix`
        Build a term similarity matrix and compute the Soft Cosine Measure.

    """
    def __init__(self, keyedvectors, threshold=0.0, exponent=2.0, kwargs=None):
        assert isinstance(keyedvectors, WordEmbeddingsKeyedVectors)
        self.keyedvectors = keyedvectors
        self.threshold = threshold
        self.exponent = exponent
        self.kwargs = kwargs or {}
        super(WordEmbeddingSimilarityIndex, self).__init__()

    def most_similar(self, t1, topn=10):
        if t1 not in self.keyedvectors.vocab:
            logger.debug('an out-of-dictionary term "%s"', t1)
        else:
            most_similar = self.keyedvectors.most_similar(positive=[t1], topn=topn, **self.kwargs)
            for t2, similarity in most_similar:
                if similarity > self.threshold:
                    yield (t2, similarity**self.exponent)


class Word2VecKeyedVectors(WordEmbeddingsKeyedVectors):
    """Mapping between words and vectors for the :class:`~gensim.models.Word2Vec` model.
    Used to perform operations on the vectors such as vector lookup, distance, similarity etc.

    """
    def save_word2vec_format(self, fname, fvocab=None, binary=False, total_vec=None):
        """Store the input-hidden weight matrix in the same format used by the original
        C word2vec-tool, for compatibility.

        Parameters
        ----------
        fname : str
            The file path used to save the vectors in
        fvocab : str, optional
            Optional file path used to save the vocabulary
        binary : bool, optional
            If True, the data will be saved in binary word2vec format, else it will be saved in plain text.
        total_vec : int, optional
            Optional parameter to explicitly specify total no. of vectors
            (in case word vectors are appended with document vectors afterwards).

        """
        # from gensim.models.word2vec import save_word2vec_format
        _save_word2vec_format(
            fname, self.vocab, self.vectors, fvocab=fvocab, binary=binary, total_vec=total_vec)

    @classmethod
    def load_word2vec_format(cls, fname, fvocab=None, binary=False, encoding='utf8', unicode_errors='strict',
                             limit=None, datatype=REAL):
        """Load the input-hidden weight matrix from the original C word2vec-tool format.

        Warnings
        --------
        The information stored in the file is incomplete (the binary tree is missing),
        so while you can query for word similarity etc., you cannot continue training
        with a model loaded this way.

        Parameters
        ----------
        fname : str
            The file path to the saved word2vec-format file.
        fvocab : str, optional
            File path to the vocabulary.Word counts are read from `fvocab` filename, if set
            (this is the file generated by `-save-vocab` flag of the original C tool).
        binary : bool, optional
            If True, indicates whether the data is in binary word2vec format.
        encoding : str, optional
            If you trained the C model using non-utf8 encoding for words, specify that encoding in `encoding`.
        unicode_errors : str, optional
            default 'strict', is a string suitable to be passed as the `errors`
            argument to the unicode() (Python 2.x) or str() (Python 3.x) function. If your source
            file may include word tokens truncated in the middle of a multibyte unicode character
            (as is common from the original word2vec.c tool), 'ignore' or 'replace' may help.
        limit : int, optional
            Sets a maximum number of word-vectors to read from the file. The default,
            None, means read all.
        datatype : type, optional
            (Experimental) Can coerce dimensions to a non-default float type (such as `np.float16`) to save memory.
            Such types may result in much slower bulk operations or incompatibility with optimized routines.)

        Returns
        -------
        :class:`~gensim.models.keyedvectors.Word2VecKeyedVectors`
            Loaded model.

        """
        # from gensim.models.word2vec import load_word2vec_format
        return _load_word2vec_format(
            cls, fname, fvocab=fvocab, binary=binary, encoding=encoding, unicode_errors=unicode_errors,
            limit=limit, datatype=datatype)

    def get_keras_embedding(self, train_embeddings=False):
        """Get a Keras 'Embedding' layer with weights set as the Word2Vec model's learned word embeddings.

        Parameters
        ----------
        train_embeddings : bool
            If False, the weights are frozen and stopped from being updated.
            If True, the weights can/will be further trained/updated.

        Returns
        -------
        `keras.layers.Embedding`
            Embedding layer.

        Raises
        ------
        ImportError
            If `Keras <https://pypi.org/project/Keras/>`_ not installed.

        Warnings
        --------
        Current method work only if `Keras <https://pypi.org/project/Keras/>`_ installed.

        """
        try:
            from keras.layers import Embedding
        except ImportError:
            raise ImportError("Please install Keras to use this function")
        weights = self.vectors

        # set `trainable` as `False` to use the pretrained word embedding
        # No extra mem usage here as `Embedding` layer doesn't create any new matrix for weights
        layer = Embedding(
            input_dim=weights.shape[0], output_dim=weights.shape[1],
            weights=[weights], trainable=train_embeddings
        )
        return layer

    @classmethod
    def load(cls, fname_or_handle, **kwargs):
        model = super(WordEmbeddingsKeyedVectors, cls).load(fname_or_handle, **kwargs)
        if isinstance(model, FastTextKeyedVectors):
            if not hasattr(model, 'compatible_hash'):
                model.compatible_hash = False

        return model


KeyedVectors = Word2VecKeyedVectors  # alias for backward compatibility


class Doc2VecKeyedVectors(BaseKeyedVectors):

    def __init__(self, vector_size, mapfile_path):
        super(Doc2VecKeyedVectors, self).__init__(vector_size=vector_size)
        self.doctags = {}  # string -> Doctag (only filled if necessary)
        self.max_rawint = -1  # highest rawint-indexed doctag
        self.offset2doctag = []  # int offset-past-(max_rawint+1) -> String (only filled if necessary)
        self.count = 0
        self.vectors_docs = []
        self.mapfile_path = mapfile_path
        self.vector_size = vector_size
        self.vectors_docs_norm = None

    @property
    def index2entity(self):
        return self.offset2doctag

    @index2entity.setter
    def index2entity(self, value):
        self.offset2doctag = value

    @property
    @deprecated("Attribute will be removed in 4.0.0, use docvecs.vectors_docs instead")
    def doctag_syn0(self):
        return self.vectors_docs

    @property
    @deprecated("Attribute will be removed in 4.0.0, use docvecs.vectors_docs_norm instead")
    def doctag_syn0norm(self):
        return self.vectors_docs_norm

    def __getitem__(self, index):
        """Get vector representation of `index`.

        Parameters
        ----------
        index : {str, list of str}
            Doctag or sequence of doctags.

        Returns
        -------
        numpy.ndarray
            Vector representation for `index` (1D if `index` is string, otherwise - 2D).

        """
        if index in self:
            if isinstance(index, string_types + integer_types + (integer,)):
                return self.vectors_docs[self._int_index(index, self.doctags, self.max_rawint)]
            return vstack([self[i] for i in index])
        raise KeyError("tag '%s' not seen in training corpus/invalid" % index)

    def __contains__(self, index):
        if isinstance(index, integer_types + (integer,)):
            return index < self.count
        else:
            return index in self.doctags

    def __len__(self):
        return self.count

    def save(self, *args, **kwargs):
        """Save object.

        Parameters
        ----------
        fname : str
            Path to the output file.

        See Also
        --------
        :meth:`~gensim.models.keyedvectors.Doc2VecKeyedVectors.load`
            Load object.

        """
        # don't bother storing the cached normalized vectors
        kwargs['ignore'] = kwargs.get('ignore', ['vectors_docs_norm'])
        super(Doc2VecKeyedVectors, self).save(*args, **kwargs)

    def init_sims(self, replace=False):
        """Precompute L2-normalized vectors.

        Parameters
        ----------
        replace : bool, optional
            If True - forget the original vectors and only keep the normalized ones = saves lots of memory!

        Warnings
        --------
        You **cannot continue training** after doing a replace.
        The model becomes effectively read-only: you can call
        :meth:`~gensim.models.keyedvectors.Doc2VecKeyedVectors.most_similar`,
        :meth:`~gensim.models.keyedvectors.Doc2VecKeyedVectors.similarity`, etc., but not train and infer_vector.

        """
        if getattr(self, 'vectors_docs_norm', None) is None or replace:
            logger.info("precomputing L2-norms of doc weight vectors")
            if not replace and self.mapfile_path:
                self.vectors_docs_norm = np_memmap(
                    self.mapfile_path + '.vectors_docs_norm', dtype=REAL,
                    mode='w+', shape=self.vectors_docs.shape)
            else:
                self.vectors_docs_norm = _l2_norm(self.vectors_docs, replace=replace)

    def most_similar(self, positive=None, negative=None, topn=10, clip_start=0, clip_end=None, indexer=None):
        """Find the top-N most similar docvecs from the training set.
        Positive docvecs contribute positively towards the similarity, negative docvecs negatively.

        This method computes cosine similarity between a simple mean of the projection
        weight vectors of the given docs. Docs may be specified as vectors, integer indexes
        of trained docvecs, or if the documents were originally presented with string tags,
        by the corresponding tags.

        TODO: Accept vectors of out-of-training-set docs, as if from inference.

        Parameters
        ----------
        positive : list of {str, int}, optional
            List of doctags/indexes that contribute positively.
        negative : list of {str, int}, optional
            List of doctags/indexes that contribute negatively.
        topn : int, optional
            Number of top-N similar docvecs to return.
        clip_start : int
            Start clipping index.
        clip_end : int
            End clipping index.

        Returns
        -------
        list of ({str, int}, float)
            Sequence of (doctag/index, similarity).

        """
        if positive is None:
            positive = []
        if negative is None:
            negative = []

        self.init_sims()
        clip_end = clip_end or len(self.vectors_docs_norm)

        if isinstance(positive, string_types + integer_types + (integer,)) and not negative:
            # allow calls like most_similar('dog'), as a shorthand for most_similar(['dog'])
            positive = [positive]

        # add weights for each doc, if not already present; default to 1.0 for positive and -1.0 for negative docs
        positive = [
            (doc, 1.0) if isinstance(doc, string_types + integer_types + (ndarray, integer))
            else doc for doc in positive
        ]
        negative = [
            (doc, -1.0) if isinstance(doc, string_types + integer_types + (ndarray, integer))
            else doc for doc in negative
        ]

        # compute the weighted average of all docs
        all_docs, mean = set(), []
        for doc, weight in positive + negative:
            if isinstance(doc, ndarray):
                mean.append(weight * doc)
            elif doc in self.doctags or doc < self.count:
                mean.append(weight * self.vectors_docs_norm[self._int_index(doc, self.doctags, self.max_rawint)])
                all_docs.add(self._int_index(doc, self.doctags, self.max_rawint))
            else:
                raise KeyError("doc '%s' not in trained set" % doc)
        if not mean:
            raise ValueError("cannot compute similarity with no input")
        mean = matutils.unitvec(array(mean).mean(axis=0)).astype(REAL)

        if indexer is not None:
            return indexer.most_similar(mean, topn)

        dists = dot(self.vectors_docs_norm[clip_start:clip_end], mean)
        if not topn:
            return dists
        best = matutils.argsort(dists, topn=topn + len(all_docs), reverse=True)
        # ignore (don't return) docs from the input
        result = [
            (self._index_to_doctag(sim + clip_start, self.offset2doctag, self.max_rawint), float(dists[sim]))
            for sim in best
            if (sim + clip_start) not in all_docs
        ]
        return result[:topn]

    def doesnt_match(self, docs):
        """Which document from the given list doesn't go with the others from the training set?

        TODO: Accept vectors of out-of-training-set docs, as if from inference.

        Parameters
        ----------
        docs : list of {str, int}
            Sequence of doctags/indexes.

        Returns
        -------
        {str, int}
            Doctag/index of the document farthest away from the mean of all the documents.

        """
        self.init_sims()

        docs = [doc for doc in docs if doc in self.doctags or 0 <= doc < self.count]  # filter out unknowns
        logger.debug("using docs %s", docs)
        if not docs:
            raise ValueError("cannot select a doc from an empty list")
        vectors = vstack(
            self.vectors_docs_norm[self._int_index(doc, self.doctags, self.max_rawint)] for doc in docs).astype(REAL)
        mean = matutils.unitvec(vectors.mean(axis=0)).astype(REAL)
        dists = dot(vectors, mean)
        return sorted(zip(dists, docs))[0][1]

    def similarity(self, d1, d2):
        """Compute cosine similarity between two docvecs from the training set.

        TODO: Accept vectors of out-of-training-set docs, as if from inference.

        Parameters
        ----------
        d1 : {int, str}
            Doctag/index of document.
        d2 : {int, str}
            Doctag/index of document.

        Returns
        -------
        float
            The cosine similarity between the vectors of the two documents.

        """
        return dot(matutils.unitvec(self[d1]), matutils.unitvec(self[d2]))

    def n_similarity(self, ds1, ds2):
        """Compute cosine similarity between two sets of docvecs from the trained set.

        TODO: Accept vectors of out-of-training-set docs, as if from inference.

        Parameters
        ----------
        ds1 : list of {str, int}
            Set of document as sequence of doctags/indexes.
        ds2 : list of {str, int}
            Set of document as sequence of doctags/indexes.

        Returns
        -------
        float
            The cosine similarity between the means of the documents in each of the two sets.

        """
        v1 = [self[doc] for doc in ds1]
        v2 = [self[doc] for doc in ds2]
        return dot(matutils.unitvec(array(v1).mean(axis=0)), matutils.unitvec(array(v2).mean(axis=0)))

    def distance(self, d1, d2):
        """
        Compute cosine distance between two documents.

        """
        return 1 - self.similarity(d1, d2)

    # required by base keyed vectors class
    def distances(self, d1, other_docs=()):
        """Compute cosine distances from given `d1` to all documents in `other_docs`.

        TODO: Accept vectors of out-of-training-set docs, as if from inference.

        Parameters
        ----------
        d1 : {str, numpy.ndarray}
            Doctag/index of document.
        other_docs : iterable of {str, int}
            Sequence of doctags/indexes.
            If None or empty, distance of `d1` from all doctags in vocab is computed (including itself).

        Returns
        -------
        numpy.array
            Array containing distances to all documents in `other_docs` from input `d1`.

        """
        input_vector = self[d1]
        if not other_docs:
            other_vectors = self.vectors_docs
        else:
            other_vectors = self[other_docs]
        return 1 - WordEmbeddingsKeyedVectors.cosine_similarities(input_vector, other_vectors)

    def similarity_unseen_docs(self, model, doc_words1, doc_words2, alpha=None, min_alpha=None, steps=None):
        """Compute cosine similarity between two post-bulk out of training documents.

        Parameters
        ----------
        model : :class:`~gensim.models.doc2vec.Doc2Vec`
            An instance of a trained `Doc2Vec` model.
        doc_words1 : list of str
            Input document.
        doc_words2 : list of str
            Input document.
        alpha : float, optional
            The initial learning rate.
        min_alpha : float, optional
            Learning rate will linearly drop to `min_alpha` as training progresses.
        steps : int, optional
            Number of epoch to train the new document.

        Returns
        -------
        float
            The cosine similarity between `doc_words1` and `doc_words2`.

        """
        d1 = model.infer_vector(doc_words=doc_words1, alpha=alpha, min_alpha=min_alpha, steps=steps)
        d2 = model.infer_vector(doc_words=doc_words2, alpha=alpha, min_alpha=min_alpha, steps=steps)
        return dot(matutils.unitvec(d1), matutils.unitvec(d2))

    def save_word2vec_format(self, fname, prefix='*dt_', fvocab=None,
                             total_vec=None, binary=False, write_first_line=True):
        """Store the input-hidden weight matrix in the same format used by the original
        C word2vec-tool, for compatibility.

        Parameters
        ----------
        fname : str
            The file path used to save the vectors in.
        prefix : str, optional
            Uniquely identifies doctags from word vocab, and avoids collision
            in case of repeated string in doctag and word vocab.
        fvocab : str, optional
            UNUSED.
        total_vec : int, optional
            Explicitly specify total no. of vectors
            (in case word vectors are appended with document vectors afterwards)
        binary : bool, optional
            If True, the data will be saved in binary word2vec format, else it will be saved in plain text.
        write_first_line : bool, optional
            Whether to print the first line in the file. Useful when saving doc-vectors after word-vectors.

        """
        total_vec = total_vec or len(self)
        with utils.smart_open(fname, 'ab') as fout:
            if write_first_line:
                logger.info("storing %sx%s projection weights into %s", total_vec, self.vectors_docs.shape[1], fname)
                fout.write(utils.to_utf8("%s %s\n" % (total_vec, self.vectors_docs.shape[1])))
            # store as in input order
            for i in range(len(self)):
                doctag = u"%s%s" % (prefix, self._index_to_doctag(i, self.offset2doctag, self.max_rawint))
                row = self.vectors_docs[i]
                if binary:
                    fout.write(utils.to_utf8(doctag) + b" " + row.tostring())
                else:
                    fout.write(utils.to_utf8("%s %s\n" % (doctag, ' '.join("%f" % val for val in row))))

    @staticmethod
    def _int_index(index, doctags, max_rawint):
        """Get int index for either string or int index."""
        if isinstance(index, integer_types + (integer,)):
            return index
        else:
            return max_rawint + 1 + doctags[index].offset

    @staticmethod
    def _index_to_doctag(i_index, offset2doctag, max_rawint):
        """Get string key for given `i_index`, if available. Otherwise return raw int doctag (same int)."""
        candidate_offset = i_index - max_rawint - 1
        if 0 <= candidate_offset < len(offset2doctag):
            return offset2doctag[candidate_offset]
        else:
            return i_index

    # for backward compatibility
    def index_to_doctag(self, i_index):
        """Get string key for given `i_index`, if available. Otherwise return raw int doctag (same int)."""
        candidate_offset = i_index - self.max_rawint - 1
        if 0 <= candidate_offset < len(self.offset2doctag):
            return self.offset2doctag[candidate_offset]
        else:
            return i_index

    # for backward compatibility
    def int_index(self, index, doctags, max_rawint):
        """Get int index for either string or int index"""
        if isinstance(index, integer_types + (integer,)):
            return index
        else:
            return max_rawint + 1 + doctags[index].offset


class FastTextKeyedVectors(WordEmbeddingsKeyedVectors):
    """Vectors and vocab for :class:`~gensim.models.fasttext.FastText`.

    Implements significant parts of the FastText algorithm.  For example,
    the :func:`word_vec` calculates vectors for out-of-vocabulary (OOV)
    entities.  FastText achieves this by keeping vectors for ngrams:
    adding the vectors for the ngrams of an entity yields the vector for the
    entity.

    Similar to a hashmap, this class keeps a fixed number of buckets, and
    maps all ngrams to buckets using a hash function.

    This class also provides an abstraction over the hash functions used by
    Gensim's FastText implementation over time.  The hash function connects
    ngrams to buckets.  Originally, the hash function was broken and
    incompatible with Facebook's implementation.  The current hash is fully
    compatible.

    Parameters
    ----------
    vector_size : int
        The dimensionality of all vectors.
    min_n : int
        The minimum number of characters in an ngram
    max_n : int
        The maximum number of characters in an ngram
    bucket : int
        The number of buckets.
    compatible_hash : boolean
        If True, uses the Facebook-compatible hash function instead of the
        Gensim backwards-compatible hash function.

    Attributes
    ----------
    vectors_vocab : np.array
        Each row corresponds to a vector for an entity in the vocabulary.
        Columns correspond to vector dimensions.
    vectors_vocab_norm : np.array
        Same as vectors_vocab, but the vectors are L2 normalized.
    vectors_ngrams : np.array
        A vector for each ngram across all entities in the vocabulary.
        Each row is a vector that corresponds to a bucket.
        Columns correspond to vector dimensions.
    vectors_ngrams_norm : np.array
        Same as vectors_ngrams, but the vectors are L2 normalized.
        Under some conditions, may actually be the same matrix as
        vectors_ngrams, e.g. if :func:`init_sims` was called with
        replace=True.
    buckets_word : dict
        Maps vocabulary items (by their index) to the buckets they occur in.

    """
    def __init__(self, vector_size, min_n, max_n, bucket, compatible_hash):
        super(FastTextKeyedVectors, self).__init__(vector_size=vector_size)
        self.vectors_vocab = None
        self.vectors_vocab_norm = None
        self.vectors_ngrams = None
        self.vectors_ngrams_norm = None
        self.buckets_word = None
        self.min_n = min_n
        self.max_n = max_n
        self.bucket = bucket
        self.compatible_hash = compatible_hash

    @classmethod
    def load(cls, fname_or_handle, **kwargs):
        model = super(WordEmbeddingsKeyedVectors, cls).load(fname_or_handle, **kwargs)
        if not hasattr(model, 'compatible_hash'):
            model.compatible_hash = False

        if hasattr(model, 'hash2index'):
            _rollback_optimization(model)

        return model

    @property
    @deprecated("Attribute will be removed in 4.0.0, use self.vectors_vocab instead")
    def syn0_vocab(self):
        return self.vectors_vocab

    @property
    @deprecated("Attribute will be removed in 4.0.0, use self.vectors_vocab_norm instead")
    def syn0_vocab_norm(self):
        return self.vectors_vocab_norm

    @property
    @deprecated("Attribute will be removed in 4.0.0, use self.vectors_ngrams instead")
    def syn0_ngrams(self):
        return self.vectors_ngrams

    @property
    @deprecated("Attribute will be removed in 4.0.0, use self.vectors_ngrams_norm instead")
    def syn0_ngrams_norm(self):
        return self.vectors_ngrams_norm

    def __contains__(self, word):
        """Check if `word` or any character ngrams in `word` are present in the vocabulary.
        A vector for the word is guaranteed to exist if current method returns True.

        Parameters
        ----------
        word : str
            Input word.

        Returns
        -------
        bool
            True if `word` or any character ngrams in `word` are present in the vocabulary, False otherwise.

        Note
        ----
        This method **always** returns True, because of the way FastText works.

        If you want to check if a word is an in-vocabulary term, use this instead:

        .. pycon:

            >>> from gensim.test.utils import datapath
            >>> from gensim.models import FastText
            >>> cap_path = datapath("crime-and-punishment.bin")
            >>> model = FastText.load_fasttext_format(cap_path, full_model=False)
            >>> 'steamtrain' in model.wv.vocab  # If False, is an OOV term
            False

        """
        return True

    def save(self, *args, **kwargs):
        """Save object.

        Parameters
        ----------
        fname : str
            Path to the output file.

        See Also
        --------
        :meth:`~gensim.models.keyedvectors.FastTextKeyedVectors.load`
            Load object.

        """
        # don't bother storing the cached normalized vectors
        ignore_attrs = [
            'vectors_norm',
            'vectors_vocab_norm',
            'vectors_ngrams_norm',
            'buckets_word',
            'hash2index',
        ]
        kwargs['ignore'] = kwargs.get('ignore', ignore_attrs)
        super(FastTextKeyedVectors, self).save(*args, **kwargs)

    def word_vec(self, word, use_norm=False):
        """Get `word` representations in vector space, as a 1D numpy array.

        Parameters
        ----------
        word : str
            Input word
        use_norm : bool, optional
            If True - resulting vector will be L2-normalized (unit euclidean length).

        Returns
        -------
        numpy.ndarray
            Vector representation of `word`.

        Raises
        ------
        KeyError
            If word and all ngrams not in vocabulary.

        """
        if word in self.vocab:
            return super(FastTextKeyedVectors, self).word_vec(word, use_norm)
        elif self.bucket == 0:
            raise KeyError('cannot calculate vector for OOV word without ngrams')
        else:
            word_vec = np.zeros(self.vectors_ngrams.shape[1], dtype=np.float32)
            if use_norm:
                ngram_weights = self.vectors_ngrams_norm
            else:
                ngram_weights = self.vectors_ngrams
            ngram_hashes = ft_ngram_hashes(word, self.min_n, self.max_n, self.bucket, self.compatible_hash)
            if len(ngram_hashes) == 0:
                #
                # If it is impossible to extract _any_ ngrams from the input
                # word, then the best we can do is return a vector that points
                # to the origin.  The reference FB implementation does this,
                # too.
                #
                # https://github.com/RaRe-Technologies/gensim/issues/2402
                #
                logger.warning('could not extract any ngrams from %r, returning origin vector', word)
                return word_vec
            for nh in ngram_hashes:
                word_vec += ngram_weights[nh]
            return word_vec / len(ngram_hashes)

    def init_sims(self, replace=False):
        """Precompute L2-normalized vectors.

        Parameters
        ----------
        replace : bool, optional
            If True - forget the original vectors and only keep the normalized ones = saves lots of memory!

        Warnings
        --------
        You **cannot continue training** after doing a replace.
        The model becomes effectively read-only: you can call
        :meth:`~gensim.models.keyedvectors.FastTextKeyedVectors.most_similar`,
        :meth:`~gensim.models.keyedvectors.FastTextKeyedVectors.similarity`, etc., but not train.

        """
        super(FastTextKeyedVectors, self).init_sims(replace)
        if getattr(self, 'vectors_ngrams_norm', None) is None or replace:
            logger.info("precomputing L2-norms of ngram weight vectors")
            self.vectors_ngrams_norm = _l2_norm(self.vectors_ngrams, replace=replace)

    def save_word2vec_format(self, fname, fvocab=None, binary=False, total_vec=None):
        """Store the input-hidden weight matrix in the same format used by the original
        C word2vec-tool, for compatibility.

        Parameters
        ----------
        fname : str
            The file path used to save the vectors in
        fvocab : str, optional
            Optional file path used to save the vocabulary
        binary : bool, optional
            If True, the data wil be saved in binary word2vec format, else it will be saved in plain text.
        total_vec : int, optional
            Optional parameter to explicitly specify total no. of vectors
            (in case word vectors are appended with document vectors afterwards).

        """
        # from gensim.models.word2vec import save_word2vec_format
        _save_word2vec_format(
            fname, self.vocab, self.vectors, fvocab=fvocab, binary=binary, total_vec=total_vec)

    def init_ngrams_weights(self, seed):
        """Initialize the vocabulary and ngrams weights prior to training.

        Creates the weight matrices and initializes them with uniform random values.

        Parameters
        ----------
        seed : float
            The seed for the PRNG.

        Note
        ----
        Call this **after** the vocabulary has been fully initialized.

        """
        self.buckets_word = _process_fasttext_vocab(
            self.vocab.items(),
            self.min_n,
            self.max_n,
            self.bucket,
            self.compatible_hash,
        )

        rand_obj = np.random
        rand_obj.seed(seed)

        lo, hi = -1.0 / self.vector_size, 1.0 / self.vector_size
        vocab_shape = (len(self.vocab), self.vector_size)
        ngrams_shape = (self.bucket, self.vector_size)
        self.vectors_vocab = rand_obj.uniform(lo, hi, vocab_shape).astype(REAL)

        #
        # We could have initialized vectors_ngrams at construction time, but we
        # do it here for two reasons:
        #
        # 1. The constructor does not have access to the random seed
        # 2. We want to use the same rand_obj to fill vectors_vocab _and_
        #    vectors_ngrams, and vectors_vocab cannot happen at construction
        #    time because the vocab is not initialized at that stage.
        #
        self.vectors_ngrams = rand_obj.uniform(lo, hi, ngrams_shape).astype(REAL)

    def update_ngrams_weights(self, seed, old_vocab_len):
        """Update the vocabulary weights for training continuation.

        Parameters
        ----------
        seed : float
            The seed for the PRNG.
        old_vocab_length : int
            The length of the vocabulary prior to its update.

        Note
        ----
        Call this **after** the vocabulary has been updated.

        """
        self.buckets_word = _process_fasttext_vocab(
            self.vocab.items(),
            self.min_n,
            self.max_n,
            self.bucket,
            self.compatible_hash,
        )

        rand_obj = np.random
        rand_obj.seed(seed)

        new_vocab = len(self.vocab) - old_vocab_len
        self.vectors_vocab = _pad_random(self.vectors_vocab, new_vocab, rand_obj)

    def init_post_load(self, vectors):
        """Perform initialization after loading a native Facebook model.

        Expects that the vocabulary (self.vocab) has already been initialized.

        Parameters
        ----------
        vectors : np.array
            A matrix containing vectors for all the entities, including words
            and ngrams.  This comes directly from the binary model.
            The order of the vectors must correspond to the indices in
            the vocabulary.
        match_gensim : boolean, optional
            No longer supported.

        """
        vocab_words = len(self.vocab)
        assert vectors.shape[0] == vocab_words + self.bucket, 'unexpected number of vectors'
        assert vectors.shape[1] == self.vector_size, 'unexpected vector dimensionality'

        #
        # The incoming vectors contain vectors for both words AND
        # ngrams.  We split them into two separate matrices, because our
        # implementation treats them differently.
        #
        self.vectors = np.array(vectors[:vocab_words, :])
        self.vectors_vocab = np.array(vectors[:vocab_words, :])
        self.vectors_ngrams = np.array(vectors[vocab_words:, :])
        self.buckets_word = None  # This can get initialized later

        self.adjust_vectors()

    def adjust_vectors(self):
        """Adjust the vectors for words in the vocabulary.

        The adjustment relies on the vectors of the ngrams making up each
        individual word.

        """
        if self.bucket == 0:
            return

        for w, v in self.vocab.items():
            word_vec = np.copy(self.vectors_vocab[v.index])
            ngram_hashes = ft_ngram_hashes(w, self.min_n, self.max_n, self.bucket, self.compatible_hash)
            for nh in ngram_hashes:
                word_vec += self.vectors_ngrams[nh]
            word_vec /= len(ngram_hashes) + 1
            self.vectors[v.index] = word_vec

    @property
    @deprecated("Attribute will be removed in 4.0.0, use self.bucket instead")
    def num_ngram_vectors(self):
        return self.bucket


def _process_fasttext_vocab(iterable, min_n, max_n, num_buckets, compatible_hash):
    """
    Performs a common operation for FastText weight initialization and
    updates: scan the vocabulary, calculate ngrams and their hashes, keep
    track of new ngrams, the buckets that each word relates to via its
    ngrams, etc.

    Parameters
    ----------
    iterable : list
        A list of (word, :class:`Vocab`) tuples.
    min_n : int
        The minimum length of ngrams.
    max_n : int
        The maximum length of ngrams.
    num_buckets : int
        The number of buckets used by the model.
    compatible_hash : boolean
        True for compatibility with the Facebook implementation.
        False for compatibility with the old Gensim implementation.

    Returns
    -------
    dict
        Keys are indices of entities in the vocabulary (words).  Values are
        arrays containing indices into vectors_ngrams for each ngram of the
        word.

    """
    word_indices = {}

    if num_buckets == 0:
        return {v.index: np.array([], dtype=np.uint32) for w, v in iterable}

    for word, vocab in iterable:
        wi = []
        for ngram_hash in ft_ngram_hashes(word, min_n, max_n, num_buckets, compatible_hash):
            wi.append(ngram_hash)
        word_indices[vocab.index] = np.array(wi, dtype=np.uint32)

    return word_indices


def _pad_random(m, new_rows, rand):
    """Pad a matrix with additional rows filled with random values."""
    rows, columns = m.shape
    low, high = -1.0 / columns, 1.0 / columns
    suffix = rand.uniform(low, high, (new_rows, columns)).astype(REAL)
    return vstack([m, suffix])


def _l2_norm(m, replace=False):
    """Return an L2-normalized version of a matrix.

    Parameters
    ----------
    m : np.array
        The matrix to normalize.
    replace : boolean, optional
        If True, modifies the existing matrix.

    Returns
    -------
    The normalized matrix.  If replace=True, this will be the same as m.

    """
    dist = sqrt((m ** 2).sum(-1))[..., newaxis]
    if replace:
        m /= dist
        return m
    else:
        return (m / dist).astype(REAL)


def _rollback_optimization(kv):
    """Undo the optimization that pruned buckets.

    This unfortunate optimization saves memory and CPU cycles, but breaks
    compatibility with Facebook's model by introducing divergent behavior
    for OOV words.

    """
    logger.warning(
        "This saved FastText model was trained with an optimization we no longer support. "
        "The current Gensim version automatically reverses this optimization during loading. "
        "Save the loaded model to a new file and reload to suppress this message."
    )
    assert hasattr(kv, 'hash2index')
    assert hasattr(kv, 'num_ngram_vectors')

    kv.vectors_ngrams = _unpack(kv.vectors_ngrams, kv.bucket, kv.hash2index)

    #
    # We have replaced num_ngram_vectors with a property and deprecated it.
    # We can't delete it because the new attribute masks the member.
    #
    del kv.hash2index


def _unpack_copy(m, num_rows, hash2index, seed=1):
    """Same as _unpack, but makes a copy of the matrix.

    Simpler implementation, but uses more RAM.

    """
    rows, columns = m.shape
    if rows == num_rows:
        #
        # Nothing to do.
        #
        return m
    assert num_rows > rows

    rand_obj = np.random
    rand_obj.seed(seed)

    n = np.empty((0, columns), dtype=m.dtype)
    n = _pad_random(n, num_rows, rand_obj)

    for src, dst in hash2index.items():
        n[src] = m[dst]

    return n


def _unpack(m, num_rows, hash2index, seed=1):
    """Restore the array to its natural shape, undoing the optimization.

    A packed matrix contains contiguous vectors for ngrams, as well as a hashmap.
    The hash map maps the ngram hash to its index in the packed matrix.
    To unpack the matrix, we need to do several things:

    1. Restore the matrix to its "natural" shape, where the number of rows
       equals the number of buckets.
    2. Rearrange the existing rows such that the hashmap becomes the identity
       function and is thus redundant.
    3. Fill the new rows with random values.

    Parameters
    ----------

    m : np.ndarray
        The matrix to restore.
    num_rows : int
        The number of rows that this array should have.
    hash2index : dict
        the product of the optimization we are undoing.
    seed : float, optional
        The seed for the PRNG.  Will be used to initialize new rows.

    Returns
    -------
    np.array
        The unpacked matrix.

    Notes
    -----

    The unpacked matrix will reference some rows in the input matrix to save memory.
    Throw away the old matrix after calling this function, or use np.copy.

    """
    orig_rows, orig_columns = m.shape
    if orig_rows == num_rows:
        #
        # Nothing to do.
        #
        return m
    assert num_rows > orig_rows

    rand_obj = np.random
    rand_obj.seed(seed)

    #
    # Rows at the top of the matrix (the first orig_rows) will contain "packed" learned vectors.
    # Rows at the bottom of the matrix will be "free": initialized to random values.
    #
    m = _pad_random(m, num_rows - orig_rows, rand_obj)

    #
    # Swap rows to transform hash2index into the identify function.
    # There are two kinds of swaps.
    # First, rearrange the rows that belong entirely within the original matrix dimensions.
    # Second, swap out rows from the original matrix dimensions, replacing them with
    # randomly initialized values.
    #
    # N.B. We only do the swap in one direction, because doing it in both directions
    # nullifies the effect.
    #
    swap = {h: i for (h, i) in hash2index.items() if h < i < orig_rows}
    swap.update({h: i for (h, i) in hash2index.items() if h >= orig_rows})
    for h, i in swap.items():
        assert h != i
        m[[h, i]] = m[[i, h]]  # swap rows i and h

    return m
