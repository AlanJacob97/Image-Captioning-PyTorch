import dataset as ds
import model as mdl

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torchvision as vis
from torchtext import data
from torchsummary import summary
import numpy as np
from matplotlib import pyplot as plt
from keras.preprocessing.sequence import pad_sequences
from nltk.translate.bleu_score import sentence_bleu

from collections import OrderedDict as OD
from copy import copy, deepcopy


def index2word(word_index):
    index_word = dict([(idx, word) for word, idx in word_index.items()])
    return index_word

def predict_caption(model, image, max_len, tokens, device):
    input_txt = "startseq"

    for i in range(max_len):
        seq = tokens.texts_to_sequences([input_txt])[0]
        # print(seq)
        seq = torch.from_numpy(pad_sequences([seq], maxlen=max_len)).long()
        # print(seq)
        # print(image, image.shape, sep='\n')
        out = model(image.to(device), seq.t().to(device))
        out = F.softmax(out, dim=1)
        _, pred = torch.max(out, 1)
        # print(pred)
        new_word = index2word(tokens.word_index)[pred.item()]
        # print(new_word)
        input_txt += " " + new_word
        if new_word == "endseq":
            break

    return input_txt


def main():
    dir_photos = "./data/flickr8k/Flicker8k_photos/"
    file_annot = "./data/flickr8k/Flickr8k_text/Flickr8k.token.txt"

    jpg_files = ds.images_info(dir_photos)
    ann_dframe = ds.annots_info(file_annot, df=True)
    print("Dataset overview\n-------------------------------------------------------------------------------------------------------------\n")
    print(ann_dframe)
    print("\n-------------------------------------------------------------------------------------------------------------\n")


    ## Prepare captions
    print("Preparing caption data for images")
    word_count = ds.word_freq(ann_dframe)
    # print(word_count)


    ## Clean text
    print("Cleaning text ... ", end="")
    for i, cpt in enumerate(ann_dframe.caption.values):
        ann_dframe["caption"].iloc[i] = ds.clean_text(cpt)
    print("done.")
    print(ann_dframe)
    word_count = ds.word_freq(ann_dframe)
    # print(word_count)

    ## Add start and end sequence token
    ann_dframe_orig = copy(ann_dframe)
    ann_dfrm = ds.add_start_end_tokens(ann_dframe)
    print(ann_dfrm)


    vgg_net = vis.models.vgg16(pretrained="imagenet", progress=True)
    for p in vgg_net.parameters():
        p.requires_grad = False
    ## Load model parameters from path
    # vgg_net.load_state_dict(torch.load('./models/vgg16-397923af.pth'))
    ## Features in the last layer
    num_ftrs = vgg_net.classifier[-1].in_features
    print(num_ftrs)
    print(vgg_net)
    ## Remove the last classifier layer: Softmax, ReLU, Dropout
    vgg_net.classifier = vgg_net.classifier[:-1]
    # ## Net architecture
    # summary(vgg_net, input_size=(3, 224, 224))
    print(vgg_net)
    # ## Features in the last layer
    # num_ftrs = vgg_net.classifier[-1].in_features
    # print(num_ftrs)
    #
    ## Read images with specified transforms
    print("Reading images ... ", end='')
    images = ds.read_image(jpg_files, dir_photos, normalize=True, resize=224, tensor=True)
    print("done.")
    # print(images.keys())
    ## Get feature map for image tensor through VGG-16
    img_featrs = OD()
    print("Gathering images' features from last conv layer ... ", end='')
    for i, jpg_name in enumerate(images.keys()):
        with torch.no_grad():
            print(i, jpg_name)
            img_featrs[jpg_name] = vgg_net(images[jpg_name].unsqueeze(0))
    print("done.")
    # print(img_featrs, img_featrs[jpg_name].size(), sep='\n')
    print(img_featrs.keys())

    # Get features for images in our dataset from pretrained VGG-16
    features = mdl.get_features(dir_photos, read=True, download=False)
    print(features)
    
    ## Prep image tensor
    print("Prepping image tensor ... ", end="")
    fnames = []
    img_tns_list = []
    cap_list = []
    for i, jpg_name in enumerate(ann_dfrm.filename.values):
         if (i % 5) == 0:
             if jpg_name in img_featrs.keys():
                 fnames.append(jpg_name)
                 img_tns_list.append(img_featrs[jpg_name])
                 cap_list.append(ann_dfrm.iloc[i]["caption"])
    print("done.")
    print(len(img_tns_list), len(cap_list))
    img_tns = torch.cat(img_tns_list)
    print(img_tns.shape)
    print("Saving filenames list, image tensor list, captions tensor list ... ", end="")
    torch.save(fnames, 'fnames.pkl')
    torch.save(img_tns_list, 'image_tns_list.pkl')
    torch.save(cap_list, 'captions_list.pkl')
    print("done.")
    
    print("Loading fnames, image tensor list and captions tensor list ... ", end="")
    fnames = torch.load('fnames.pkl')
    img_tns_list = torch.load('image_tns_list.pkl')
    img_tns = torch.cat(img_tns_list)
    cap_list = torch.load('captions_list.pkl')
    # print(len(fnames), cap_list)
    print("done.")

    cap_seq, vocab_size, cap_max_len, tokens = ds.tokenizer(cap_list)
    n_cap = len(cap_seq)
    vald_prop, test_prop = 0.2, 0.2
    n_vald = int(n_cap * vald_prop)
    n_test = int(n_cap * test_prop)

    train_cap, valid_cap, evaln_cap = ds.split_dset(cap_seq, n_vald, n_test)
    train_ims, valid_ims, evaln_ims = ds.split_dset(img_tns, n_vald, n_test)
    # train_fnm, valid_fnm, evaln_fnm = ds.split_dset(fnames, n_vald, n_test)

    print(len(train_cap), len(valid_cap), len(evaln_cap))
    print(len(train_ims), len(valid_ims), len(evaln_ims))

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print("Using " + device)

    print("Loading model ...")
    model = torch.load('best_model.pkl')
    print(model)
    model.eval()

    # print(fnames)

    preds = []
    for feat in evaln_ims:
        preds.append(predict_caption(model, feat, cap_max_len, tokens, device))

    best_targets = []
    for p, t in zip(preds, cap_list[:n_test]):
        pred = p.split(" ")
        targ = [t.split(" ")]
        z=sentence_bleu(targ, pred, weights=(1, 0, 0, 0))
        if z > 0.50:
            print(p, t, z, sep='\n')
            print("\n")
            best_targets.append(t)
    print(best_targets)

    for cap in best_targets:
        rows = ann_dfrm.loc[ann_dfrm["caption"]==cap, "filename"]
        print(rows)


if __name__ == '__main__':
    main()