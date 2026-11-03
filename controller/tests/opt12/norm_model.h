/* Group64 trees followed by the tree of group roots. Input n is padded. */
static float nx_opt12_tree(float *p,int n){
    if(n<=64){while(n>1){for(int i=0;i<n/2;i++)p[i]=p[2*i]+p[2*i+1];n/=2;}return p[0];}
    int groups=n/64;
    for(int g=0;g<groups;g++){
        float t[64];for(int i=0;i<64;i++)t[i]=p[g*64+i];
        for(int w=64;w>1;w/=2)for(int i=0;i<w/2;i++)t[i]=t[2*i]+t[2*i+1];
        p[g]=t[0];
    }
    return nx_opt12_tree(p,groups);
}
