static void load_small(nx_weights *w,const unsigned char *base) {
memset(w,0,sizeof(*w));
w->embedding=(nx_matrix){(const int8_t *)(base+0),(const float *)(base+4096),NULL,64,64};
w->layer[0].q=(nx_matrix){(const int8_t *)(base+4352),(const float *)(base+8448),(const float *)(base+8704),64,64};
w->layer[0].k=(nx_matrix){(const int8_t *)(base+8960),(const float *)(base+13056),(const float *)(base+13312),64,64};
w->layer[0].v=(nx_matrix){(const int8_t *)(base+13568),(const float *)(base+17664),(const float *)(base+17920),64,64};
w->layer[0].o=(nx_matrix){(const int8_t *)(base+18176),(const float *)(base+22272),NULL,64,64};
w->layer[0].gate=(nx_matrix){(const int8_t *)(base+22528),(const float *)(base+26624),NULL,64,64};
w->layer[0].up=(nx_matrix){(const int8_t *)(base+26880),(const float *)(base+30976),NULL,64,64};
w->layer[0].down=(nx_matrix){(const int8_t *)(base+31232),(const float *)(base+35328),NULL,64,64};
w->layer[0].norm1=(const float *)(base+35584);
w->layer[0].norm2=(const float *)(base+35840);
w->norm=(const float *)(base+36096);
w->inv_freq=(const float *)(base+36352);
}
