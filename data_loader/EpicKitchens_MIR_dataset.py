import os
import sys
import random
import pickle
import numpy as np
import pandas as pd
sys.path.append('/apdcephfs/private_qinghonglin/video_codebase/EgoVLP/')

from base.base_dataset import TextVideoDataset
from data_loader.transforms import init_transform_dict, init_video_transform_dict

import torch
from PIL import Image
from torchvision import transforms

class MultiInstanceRetrieval(TextVideoDataset):
    def _load_metadata(self):
        split_files = {
            'train': 'EPIC_100_retrieval_train.csv',
            'val': 'EPIC_100_retrieval_test.csv',            # there is no test
            'test': 'EPIC_100_retrieval_test.csv'
        }
        split_files_sentence = {
            'train': 'EPIC_100_retrieval_train_sentence.csv',
            'val': 'EPIC_100_retrieval_test_sentence.csv',  # there is no test
            'test': 'EPIC_100_retrieval_test_sentence.csv'
        }
        noun_verb_classes_files = {
            'noun': '../EPIC_100_noun_classes.csv',
            'verb': '../EPIC_100_verb_classes.csv',
        }
        target_split_fp = split_files[self.split]
        metadata = pd.read_csv(os.path.join(self.meta_dir, target_split_fp))
        df = pd.read_csv(os.path.join(self.meta_dir, noun_verb_classes_files['noun']))
        df['key'] = df['key'].apply(lambda x: '{} {}'.format(x.split(':')[-1],' '.join(x.split(':')[:-1])) if ':' in x else x)
        noun_classes_dict = pd.Series(df.instances.values,index=df.key).to_dict()
        noun_classes_dict = {v:k for k,val in noun_classes_dict.items() for v in eval(val)}
        df = pd.read_csv(os.path.join(self.meta_dir, noun_verb_classes_files['verb']))
        verb_classes_dict = pd.Series(df.instances.values,index=df.key).to_dict()
        verb_classes_dict = {v:k for k,val in verb_classes_dict.items() for v in eval(val)}
        verb_classes_dict['bring-into'] = 'carry' # missing in the EK dict

        target_split_sentence_fp = split_files_sentence[self.split]
        metadata_sentence = pd.read_csv(os.path.join(self.meta_dir, target_split_sentence_fp))

        if self.split == 'train':
            path_relevancy = os.path.join(self.meta_dir, 'relevancy/caption_relevancy_EPIC_100_retrieval_train.pkl')
        elif self.split in ['val', 'test']:
            path_relevancy = os.path.join(self.meta_dir, 'relevancy/caption_relevancy_EPIC_100_retrieval_test.pkl')

        pkl_file = open(path_relevancy, 'rb')
        self.relevancy = 0.1
        self.relevancy_mat = pickle.load(pkl_file)

        self.metadata = metadata
        self.metadata_sentence = metadata_sentence
        self.noun_classes_dict = noun_classes_dict
        self.verb_classes_dict = verb_classes_dict

    def _get_video_path(self, sample):
        rel_video_fp = sample[2]
        full_video_fp = os.path.join(self.data_dir, rel_video_fp)

        return full_video_fp, rel_video_fp

    def _get_caption(self, idx, sample):
        # return sentence, relevancy score, idx
        if self.split == 'train':
            positive_list = np.where(self.relevancy_mat[idx] > self.relevancy)[0].tolist()
            if positive_list != []:
                pos = random.sample(positive_list, min(len(positive_list), 1))[0]
                if pos < len(self.metadata_sentence) and pos < self.relevancy_mat.shape[1]:
                    return self.metadata_sentence.iloc[pos][1], self.relevancy_mat[idx][pos], pos
            return sample[8], 1, 0

        elif self.split in ['val', 'test']:
            verb_nouns = [sample[9]]
            verb_nouns.extend(eval(sample[13]))
            if self.text_params['normalize_labels']:
                verb_norm = [self.verb_classes_dict[verb_nouns[0]]]     
                nouns_norm = [self.noun_classes_dict[n] for n in verb_nouns[1:]]
                verb_nouns = verb_norm
                verb_nouns.extend(sorted(nouns_norm))
                verb_nouns = ' '.join(verb_nouns)
            return verb_nouns, 1, -1

    def __getitem__(self, item):
        item = item % len(self.metadata)
        sample = self.metadata.iloc[item]
        video_fp, rel_fp = self._get_video_path(sample)
        caption, relation, idx = self._get_caption(item, sample)

        video_loading = self.video_params.get('loading', 'strict')
        start_frame, stop_frame = int(sample[6]), int(sample[7])

        frame_sample = 'rand'
        if self.split in ['test', 'val']:
            frame_sample = 'uniform'
        fix_start = None

        try:
            if os.path.exists(video_fp):
                # only supported for read_frames_decord_online
                imgs, idxs = self.video_reader(video_fp, start_frame, stop_frame, self.video_params['num_frames'], frame_sample,
                                               fix_start=fix_start)
            else:
                print(f"Warning: missing video file {video_fp}.")
                assert False
        except Exception as e:
            if video_loading == 'strict':
                raise ValueError(
                    f'Video loading failed for {video_fp}, video loading for this dataset is strict.') from e
            else:
                imgs = Image.new('RGB', (self.video_params['input_res'], self.video_params['input_res']), (0, 0, 0))
                imgs = transforms.ToTensor()(imgs).unsqueeze(0)

        if self.transforms is not None:
            if self.video_params['num_frames'] > 1:
                imgs = imgs.transpose(0, 1)  # [T, C, H, W] ---> [C, T, H, W]
                imgs = self.transforms(imgs)
                imgs = imgs.transpose(0, 1)  # recover
            else:
                imgs = self.transforms(imgs)

        final = torch.zeros([self.video_params['num_frames'], 3, self.video_params['input_res'],
                             self.video_params['input_res']])
        final[:imgs.shape[0]] = imgs

        meta_arr = {'raw_captions': caption, 'paths': item, 'dataset': self.dataset_name, 'video_id': rel_fp}
        data = {'video': final, 'text': caption, 'meta': meta_arr, 'relation': relation, 'item_v': item, 'item_t': idx}
        return data

if __name__ == "__main__":
    kwargs = dict(
        dataset_name="MultiInstanceRetrieval",
        text_params={
            "input": "text"
        },
        video_params={
        "input_res": 224,
        "num_frames": 4,
        "loading": "lax"
        },
        data_dir="/apdcephfs/private_qinghonglin/video_dataset/epic-kitchens/epic-kitchens-rgb-frames",
        meta_dir="epic-kitchens-100-annotations-master/retrieval_annotations",
        tsfms=init_video_transform_dict()['test'],
        reader='cv2_epic',
        split='train'
    )
    dataset = MultiInstanceRetrieval(**kwargs)
    for i in range(100):
        item = dataset[i]
        print(item.keys())
